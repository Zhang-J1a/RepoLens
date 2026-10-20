import contextlib
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from repolens.cli import main
from repolens.config import data_directory
from repolens.domain import MAX_FILE_BYTES, RepoLensError
from repolens.embeddings import LocalTfidfEmbeddingProvider, cosine_similarity
from repolens.git import GitRepository, _command, _environment, safe_repository_path
from repolens.index import DATABASE_NAME, RETRIEVAL_POLICY, IndexStore, match_expression
from repolens.retrieval import identifier_terms, query_expansion_terms, rerank_candidates
from repolens.ingestion import ingest
from repolens.parsing import parse_file


class IndexingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.repo = self.base / "source repo"
        self.repo.mkdir()
        self.data = self.base / "index"
        self.env = _environment() | {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        self.git("-c", "init.templateDir=", "init", "--quiet")
        self.write("src/service.py", 'def dispatch():\n    """oldexclusive sharedtoken"""\n    return 1\n')
        self.write("docs/a_b.md", "# Dispatch\nsharedtoken underscoreonly\n")
        self.write("docs/aXb.md", "# Other\nsharedtoken otheronly\n")
        self.write("assets/not_supported.txt", "mustnotindex\n")
        self.first = self.commit()

    def git(self, *args, input=None):
        return subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-c", "user.name=RepoLens Test",
             "-c", "user.email=test@example.invalid", "-C", str(self.repo), *args],
            env=self.env, input=input, capture_output=True, check=True, timeout=30,
        ).stdout.decode("utf-8").strip()

    def write(self, path, text):
        file = self.repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8", newline="")

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", "Test snapshot")
        return self.git("rev-parse", "HEAD")

    def test_ingestion_is_idempotent_and_does_not_change_target(self):
        status = self.git("status", "--porcelain=v1")
        index_hash = hashlib.sha256((self.repo / ".git" / "index").read_bytes()).hexdigest()
        first = ingest(self.repo, self.data, self.first)
        second = ingest(self.repo, self.data, self.first)
        self.assertEqual(first["snapshot_id"], second["snapshot_id"])
        self.assertEqual(first["stats"], second["stats"])
        self.assertEqual(first["stats"]["indexed_files"], 3)
        self.assertEqual(first["stats"]["statuses"]["unsupported_type"], 1)
        self.assertEqual(self.git("status", "--porcelain=v1"), status)
        self.assertEqual(hashlib.sha256((self.repo / ".git" / "index").read_bytes()).hexdigest(), index_hash)
        with IndexStore(self.data, writable=True) as store:
            self.assertEqual(len(store.snapshots()), 1)
            count = store.connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
            self.assertEqual(count, first["stats"]["chunks"])
            store.connection.execute("INSERT INTO chunks_fts(chunks_fts) VALUES ('integrity-check')")
            self.assertTrue(store.search("oldexclusive", first["snapshot_id"]))

    def test_dirty_untracked_deleted_files_never_change_committed_evidence(self):
        self.write("src/service.py", "raise RuntimeError('dirtyexclusive')\n")
        self.write("untracked.py", "untrackedexclusive = 42\n")
        (self.repo / "docs" / "a_b.md").unlink()
        status = self.git("status", "--porcelain=v1")
        snapshot = ingest(self.repo, self.data, self.first)["snapshot_id"]
        with IndexStore(self.data) as store:
            evidence = store.search("oldexclusive", snapshot)[0]
            self.assertEqual(evidence["path"], "src/service.py")
            self.assertEqual(evidence["commit_sha"], self.first)
            self.assertIn("return 1", evidence["text"])
            self.assertFalse(store.search("dirtyexclusive untrackedexclusive", snapshot))
            self.assertTrue(store.search("underscoreonly", snapshot))
        self.assertEqual(self.git("status", "--porcelain=v1"), status)

    def test_git_hooks_and_smudge_filters_are_not_run_during_ingestion(self):
        marker = self.base / "hook-or-filter-ran"
        hook = self.repo / ".git" / "hooks" / "post-checkout"
        hook.parent.mkdir(exist_ok=True)
        hook.write_text("#!/bin/sh\nprintf unsafe > '" + marker.as_posix() + "'\n", encoding="utf-8")
        hook.chmod(0o755)
        self.write(".gitattributes", "*.py filter=must-not-run\n")
        commit = self.commit()
        self.git("config", "filter.must-not-run.smudge", "sh '" + hook.as_posix() + "'")
        self.git("config", "filter.must-not-run.clean", "cat")
        self.git("config", "filter.must-not-run.required", "true")
        status = self.git("status", "--porcelain=v1")
        snapshot = ingest(self.repo, self.data, commit)["snapshot_id"]
        with IndexStore(self.data) as store:
            self.assertTrue(store.search("oldexclusive", snapshot))
        self.assertFalse(marker.exists())
        self.assertEqual(self.git("status", "--porcelain=v1"), status)

    def test_git_replace_refs_cannot_substitute_snapshot_source_or_history(self):
        self.write("src/service.py", "def dispatch():\n    return 'replacementexclusive'\n")
        replacement = self.commit()
        self.git("replace", self.first, replacement)
        snapshot = ingest(self.repo, self.data, self.first)["snapshot_id"]
        with IndexStore(self.data) as store:
            evidence = store.search("oldexclusive", snapshot)[0]
            self.assertEqual(evidence["commit_sha"], self.first)
            self.assertIn("oldexclusive", evidence["text"])
            self.assertFalse(store.search("replacementexclusive", snapshot))
            self.assertNotIn(replacement, {item["commit_sha"] for item in store.history(snapshot)})

    def test_snapshot_scope_and_evidence_scope_do_not_leak_versions(self):
        old = ingest(self.repo, self.data, self.first)
        self.write("src/service.py", 'def dispatch():\n    """newexclusive sharedtoken"""\n    return 2\n')
        second = self.commit()
        new = ingest(self.repo, self.data, second)
        with IndexStore(self.data) as store:
            self.assertNotEqual(old["snapshot_id"], new["snapshot_id"])
            old_evidence = store.search("oldexclusive", old["snapshot_id"])[0]
            self.assertFalse(store.search("newexclusive", old["snapshot_id"]))
            self.assertFalse(store.search("oldexclusive", new["snapshot_id"]))
            self.assertEqual(store.search("newexclusive", new["snapshot_id"])[0]["commit_sha"], second)
            with self.assertRaises(RepoLensError):
                store.evidence(old_evidence["evidence_id"], new["snapshot_id"])

    def test_multiple_local_repositories_have_separate_identities(self):
        old = ingest(self.repo, self.data)
        clone = self.base / "clone"
        self.git("clone", "--quiet", "--bare", "--local", str(self.repo), str(clone))
        new = ingest(clone, self.data)
        self.assertNotEqual(old["repository_id"], new["repository_id"])
        with IndexStore(self.data) as store:
            self.assertEqual(len(store.snapshots()), 2)
            result = store.search("oldexclusive", new["snapshot_id"])[0]
            self.assertEqual(result["repository_id"], new["repository_id"])

    def test_non_utf8_git_path_fails_closed_before_writing_index(self):
        blob = self.git("hash-object", "-w", "--stdin", input=b"unsafe path\n")
        index_entry = f"100644 {blob}\t".encode() + b"bad\xff.py\x00"
        self.git("update-index", "-z", "--index-info", input=index_entry)
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", "Non-UTF-8 path")
        with self.assertRaisesRegex(RepoLensError, "non-UTF-8"):
            ingest(self.repo, self.data)
        self.assertFalse(self.data.exists())

    def test_symlink_submodule_binary_oversize_and_parse_failures_are_reported(self):
        blob = self.git("hash-object", "-w", "--stdin", input=b"../../outside.py")
        self.git("update-index", "--add", "--cacheinfo", f"120000,{blob},link.py")
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.first},vendor")
        (self.repo / "binary.py").write_bytes(b"\x00binarystuff")
        (self.repo / "large.py").write_bytes(b"#" * (MAX_FILE_BYTES + 1))
        self.write("broken.py", "def broken(:\n    pass\n")
        self.git("add", "binary.py", "large.py", "broken.py")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", "Special entries")
        snapshot = ingest(self.repo, self.data)
        statuses = snapshot["stats"]["statuses"]
        for status in ("symlink", "submodule", "binary", "too_large", "parse_fallback"):
            self.assertEqual(statuses[status], 1)
        with IndexStore(self.data) as store:
            self.assertEqual(store.search("broken", snapshot["snapshot_id"])[0]["kind"], "python_fallback")

    def test_data_inside_target_or_git_directory_is_rejected_before_creation(self):
        for directory in (self.repo / "index", self.repo / ".git" / "index-data"):
            with self.subTest(directory=directory):
                with self.assertRaises(RepoLensError):
                    ingest(self.repo, directory)
                self.assertFalse(directory.exists())

    def test_failed_rebuild_rolls_back_records_and_fts(self):
        snapshot = ingest(self.repo, self.data)
        git = GitRepository(self.repo)
        entry = next(entry for entry in git.inventory(self.first) if entry.path == "src/service.py")
        with git.blobs() as reader:
            file = parse_file(entry, reader.read(entry))
        bad_file = replace(file, chunks=file.chunks + file.chunks)
        with IndexStore(self.data, writable=True) as store:
            before = store.search("oldexclusive", snapshot["snapshot_id"])
            with self.assertRaises(sqlite3.IntegrityError):
                store.save(git.root, snapshot["repository_id"], snapshot["snapshot_id"],
                           git.commit(self.first), [bad_file], {})
            self.assertEqual(store.search("oldexclusive", snapshot["snapshot_id"]), before)
            self.assertEqual(store.snapshot(snapshot["snapshot_id"])["stats"], snapshot["stats"])

    def test_literal_path_prefix_and_safe_query_handling(self):
        snapshot = ingest(self.repo, self.data)["snapshot_id"]
        with IndexStore(self.data) as store:
            hits = store.search("sharedtoken", snapshot, path_prefix="docs/a_")
            self.assertEqual([hit["path"] for hit in hits], ["docs/a_b.md"])
            store.search('" OR NEAR(foo*) ; DROP TABLE chunks; --', snapshot)
            self.assertTrue(store.search("oldexclusive", snapshot))
            for query in ("", "***", "a" * 4097, " ".join(f"term{i}" for i in range(65))):
                with self.subTest(query=query[:20]), self.assertRaises(RepoLensError):
                    store.search(query, snapshot)
            for limit in (0, 101):
                with self.assertRaises(RepoLensError):
                    store.search("dispatch", snapshot, limit=limit)
            with self.assertRaises(RepoLensError):
                store.search("dispatch", snapshot, path_prefix="../")

    def test_chinese_question_expands_to_code_terms(self):
        self.write("main.py", "def main():\n    return 1\n")
        self.write("book_io.py", "def load_books():\n    return []\n\ndef save_books(items):\n    return items\n")
        snapshot = ingest(self.repo, self.data, self.commit())["snapshot_id"]
        with IndexStore(self.data) as store:
            hits = store.search("这个项目的主要入口是什么？书籍数据如何读写？", snapshot, limit=10)
        paths = {item["path"] for item in hits}
        self.assertIn("main.py", paths)
        self.assertIn("book_io.py", paths)
        self.assertIn("main", query_expansion_terms("主要入口是什么？"))
        self.assertIn("read", query_expansion_terms("数据如何读取？"))

    def test_local_tfidf_provider_is_deterministic_and_round_trips(self):
        provider = LocalTfidfEmbeddingProvider()
        provider.fit(("def load_books(): return books", "def save_books(items): return items"))
        first = provider.embed("load books")
        restored = LocalTfidfEmbeddingProvider.from_model_json(provider.model_json())
        self.assertEqual(first, restored.embed("load books"))
        self.assertGreater(cosine_similarity(first, provider.embed("load_books")), 0.0)
        self.assertEqual(provider.embed("unseen vocabulary"), {})

    def test_vector_and_hybrid_search_are_snapshot_scoped(self):
        snapshot = ingest(self.repo, self.data, self.first)["snapshot_id"]
        with IndexStore(self.data) as store:
            vector = store.search_vector("oldexclusive", snapshot, limit=5)
            hybrid = store.search_hybrid("oldexclusive", snapshot, limit=5)
        self.assertTrue(vector)
        self.assertEqual(vector[0]["path"], "src/service.py")
        self.assertEqual(hybrid[0]["path"], "src/service.py")
        self.assertEqual(hybrid[0]["retrieval_method"], "hybrid")
        self.assertIsNotNone(hybrid[0]["vector_rank"])

    def test_child_snapshot_reuses_unchanged_parsed_blobs(self):
        first = ingest(self.repo, self.data, self.first)
        self.write("src/service.py", 'def dispatch():\n    """newexclusive"""\n    return 2\n')
        second_sha = self.commit()
        second = ingest(self.repo, self.data, second_sha)
        self.assertEqual(second["stats"]["index_mode"], "incremental")
        self.assertEqual(second["stats"]["base_snapshot_id"], first["snapshot_id"])
        self.assertGreaterEqual(second["stats"]["reused_files"], 3)
        self.assertEqual(second["stats"]["parsed_files"], 1)
        with IndexStore(self.data) as store:
            self.assertTrue(store.search_vector("newexclusive", second["snapshot_id"]))
            self.assertFalse(store.search_vector("oldexclusive", second["snapshot_id"]))

    def test_snapshot_indexes_and_searches_reachable_commit_history(self):
        first = ingest(self.repo, self.data, self.first)
        with IndexStore(self.data) as store:
            first_history = store.history(first["snapshot_id"])
            self.assertEqual(len(first_history), 1)
            self.assertEqual(first_history[0]["commit_sha"], self.first)
            self.assertTrue(store.search_history("Test snapshot", first["snapshot_id"]))

        self.write("src/history.py", "value = 1\n")
        self.git("add", "--all")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", "Add history fixture")
        second_sha = self.git("rev-parse", "HEAD")
        second = ingest(self.repo, self.data, second_sha)
        with IndexStore(self.data) as store:
            second_history = store.history(second["snapshot_id"])
            self.assertEqual(len(second_history), 2)
            self.assertEqual(second_history[0]["commit_sha"], second_sha)
            self.assertEqual(second_history[1]["commit_sha"], self.first)
            result = store.search_history("Add history fixture", second["snapshot_id"])
            self.assertEqual(result[0]["commit_sha"], second_sha)
            self.assertFalse(store.search_history("Add history fixture", first["snapshot_id"]))

    def test_snapshot_records_local_branches_containing_commit(self):
        snapshot = ingest(self.repo, self.data, self.first)
        branch = self.git("branch", "--show-current")
        self.assertIn(branch, snapshot["stats"]["local_branches"])

    def test_evidence_integrity_failure_is_not_silently_returned(self):
        snapshot = ingest(self.repo, self.data)["snapshot_id"]
        with IndexStore(self.data, writable=True) as store:
            evidence = store.search("oldexclusive", snapshot)[0]
            store.connection.execute("UPDATE files SET text='corrupt' WHERE path='src/service.py'")
            with self.assertRaises(RepoLensError):
                store.evidence(evidence["evidence_id"], snapshot)

    def test_result_limit_does_not_change_candidate_budget_or_ranking_prefix(self):
        for number in range(120):
            self.write(f"docs/budget-{number:03d}.md", f"# Item {number}\ncommonbudget\n")
        snapshot = ingest(self.repo, self.data, self.commit())["snapshot_id"]
        with IndexStore(self.data) as store:
            with patch("repolens.index.rerank_candidates", wraps=rerank_candidates) as ranker:
                large = store.search("commonbudget", snapshot, limit=10)
                small = store.search("commonbudget", snapshot, limit=5)
                single = store.search("commonbudget", snapshot, limit=1)
            self.assertEqual([len(call.args[0]) for call in ranker.call_args_list], [100, 100, 100])
            self.assertEqual(small, large[:5])
            self.assertEqual(single, large[:1])

    def test_corrupt_empty_or_reversed_evidence_spans_are_rejected(self):
        snapshot = ingest(self.repo, self.data)["snapshot_id"]
        with IndexStore(self.data, writable=True) as store:
            evidence_id = store.search("oldexclusive", snapshot)[0]["evidence_id"]
            store.connection.execute("PRAGMA ignore_check_constraints=ON")
            for start, end in ((0, 0), (2, 1), (1, 999)):
                with self.subTest(start=start, end=end):
                    store.connection.execute(
                        "UPDATE chunks SET line_start=?, line_end=?, text='' WHERE id=?",
                        (start, end, evidence_id),
                    )
                    with self.assertRaisesRegex(RepoLensError, "source-span"):
                        store.evidence(evidence_id, snapshot)

    def test_missing_ref_or_repository_leaves_no_index(self):
        for path, ref in ((self.repo, "missing-ref"), (self.base / "absent", "HEAD"), (self.base, "HEAD")):
            with self.subTest(path=path, ref=ref), self.assertRaises(RepoLensError):
                ingest(path, self.data, ref)
            self.assertFalse(self.data.exists())

    def test_commit_authorship_timestamp_is_normalized_to_utc(self):
        self.write("date.py", "value = 1\n")
        self.git("add", "date.py")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", "Timezone test",
                 "--date=2020-01-01T12:00:00+05:30")
        commit = GitRepository(self.repo).commit("HEAD")
        self.assertEqual(commit.authored_at, "2020-01-01T06:30:00+00:00")

    def test_cli_ingest_search_evidence_and_snapshots_return_json(self):
        def call(*args):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([*args, "--data-dir", str(self.data)]), 0)
            return json.loads(output.getvalue())
        snapshot = call("ingest", str(self.repo), "--ref", self.first)["snapshot_id"]
        search_result = call("search", "oldexclusive", "--snapshot", snapshot)
        self.assertEqual(search_result["retrieval"], RETRIEVAL_POLICY)
        result = search_result["results"][0]
        evidence = call("evidence", result["evidence_id"], "--snapshot", snapshot)
        self.assertEqual(evidence["text"], result["text"])
        self.assertEqual(call("snapshots")["snapshots"][0]["snapshot_id"], snapshot)
        history_result = call("history", "Test snapshot", "--snapshot", snapshot)
        self.assertEqual(history_result["results"][0]["commit_sha"], self.first)

    def test_cli_ask_indexes_repository_and_answers_in_one_workflow(self):
        def call():
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main([
                    "ask", "What does dispatch do?", "--repository", str(self.repo),
                    "--ref", self.first, "--provider", "mock", "--data-dir", str(self.data),
                ]), 0)
            return json.loads(output.getvalue())

        first_result = call()
        second_result = call()
        self.assertEqual(first_result["answer"]["status"], "answered")
        self.assertEqual(first_result["answer"]["provider"], "mock")
        self.assertEqual(first_result["workflow"]["commit_sha"], self.first)
        self.assertEqual(first_result["workflow"]["snapshot_id"], first_result["snapshot_id"])
        self.assertEqual(first_result["workflow"]["index_action"], "created")
        self.assertEqual(second_result["workflow"]["index_action"], "reused")
        self.assertEqual(second_result["workflow"]["snapshot_id"], first_result["workflow"]["snapshot_id"])
        self.assertEqual(second_result["telemetry"]["provider"], "mock")

    def test_cli_chat_handles_multiple_turns_and_exit_command(self):
        output = io.StringIO()
        user_input = io.StringIO("What does dispatch do?\n:quit\n")
        self.assertEqual(main([
            "chat", "--repository", str(self.repo), "--ref", self.first,
            "--provider", "mock", "--data-dir", str(self.data),
        ], input_stream=user_input, output_stream=output), 0)
        text = output.getvalue()
        self.assertIn("RepoLens chat", text)
        self.assertIn("[第 1 轮] answered", text)
        self.assertIn("会话结束", text)

    def test_cli_operation_errors_are_stderr_without_traceback(self):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            result = main(["search", "query", "--snapshot", "unknown", "--data-dir", str(self.data)])
        self.assertEqual(result, 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Index not found", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())
        self.assertFalse(self.data.exists())


class ConfigurationTests(unittest.TestCase):
    def test_data_location_precedence_and_platform_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {"REPOLENS_DATA_DIR": temporary}):
                self.assertEqual(data_directory(), Path(temporary).resolve())
                self.assertEqual(data_directory(Path(temporary) / "explicit"), Path(temporary, "explicit").resolve())
        with patch.dict(os.environ, {"REPOLENS_DATA_DIR": ""}):
            self.assertTrue(data_directory().is_absolute())

    def test_environment_blocks_git_redirection_and_lazy_fetch(self):
        with patch.dict(os.environ, {"GIT_DIR": "wrong", "GIT_WORK_TREE": "wrong", "GIT_NO_LAZY_FETCH": "0"}):
            env = _environment()
        self.assertNotIn("GIT_DIR", env)
        self.assertNotIn("GIT_WORK_TREE", env)
        self.assertEqual(env["GIT_NO_LAZY_FETCH"], "1")
        self.assertEqual(env["GIT_OPTIONAL_LOCKS"], "0")

    def test_git_command_allows_only_the_selected_repository(self):
        command = _command(Path("D:/selected-repository"), "rev-parse", "HEAD")
        self.assertIn("safe.directory=" + str(Path("D:/selected-repository")), command)

    def test_unsafe_paths_and_fts_operators_are_not_accepted_as_control_input(self):
        for path in ("../a.py", "/a.py", "C:/a.py", "a\\b.py", "a//b.py", "./a.py", ""):
            with self.subTest(path=path):
                self.assertFalse(safe_repository_path(path))
        self.assertTrue(safe_repository_path("src/a b.py"))
        self.assertEqual(
            match_expression("foo_bar OR baz*"),
            '"foo" OR "bar" OR "OR" OR "baz" OR "foo_bar"',
        )

    def test_unknown_database_schema_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            connection = sqlite3.connect(directory / DATABASE_NAME)
            with connection:
                connection.execute("PRAGMA user_version = 999")
            connection.close()
            with self.assertRaises(RepoLensError):
                IndexStore(directory, writable=True)


class RetrievalRankingTests(unittest.TestCase):
    def test_identifier_terms_preserve_code_names(self):
        self.assertEqual(
            identifier_terms("Flask.test_client and before_request"),
            ("flask.test_client", "and", "before_request"),
        )

    def test_reranking_rewards_coverage_without_repository_specific_rules(self):
        candidates = [
            {"id": "b", "path": "tests/test_client.py", "symbol": "unrelated", "line_start": 1,
             "text": "request context", "bm25_score": -20.0},
            {"id": "a", "path": "src/app.py", "symbol": "Flask.test_client", "line_start": 1,
             "text": "with block preserves request context", "bm25_score": -15.0},
        ]
        ranked = rerank_candidates(candidates, "Flask.test_client with request context", 2)
        self.assertEqual([item["id"] for item in ranked], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
