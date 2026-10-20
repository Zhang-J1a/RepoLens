import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from repolens.benchmark import run_benchmark
from repolens.domain import RepoLensError
from repolens.git import _environment
from repolens.ingestion import ingest


class GenerationBenchmarkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        env = _environment() | {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        def git(*args):
            return subprocess.run(["git", "-c", "init.templateDir=", "-C", str(self.repo), *args],
                                  env=env, capture_output=True, check=True, timeout=30).stdout.decode().strip()
        git("init", "-q")
        (self.repo / "service.py").write_text("def dispatch():\n    return 'private-source-marker'\n", encoding="utf-8")
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture", "--no-gpg-sign")
        self.sha = git("rev-parse", "HEAD")
        self.directory = self.root / "index"
        self.snapshot = ingest(self.repo, self.directory, self.sha)["snapshot_id"]
        self.dataset = self.root / "cases.jsonl"
        self.cases = [{"id": str(i), "query": "dispatch", "commit_sha": self.sha,
                       "answerable": True, "category": "identifier"} for i in range(2)]
        self.write_dataset()
        self.output = self.root / "run"

    def write_dataset(self):
        self.dataset.write_text("".join(json.dumps(case) + "\n" for case in self.cases), encoding="utf-8")

    def run_cases(self, **options):
        return run_benchmark(self.dataset, self.directory, self.snapshot, self.output,
                             strategies=("hybrid",), **options)

    def test_resume_does_not_repeat_completed_calls_or_save_source_context(self):
        first = self.run_cases()
        self.assertEqual(first["completed"], 2)
        self.assertIsNone(first["cost"])
        raw = (self.output / "events.jsonl").read_bytes()
        self.assertNotIn(b"private-source-marker", raw)
        self.assertNotIn(b'"rendered"', raw)
        with patch("repolens.benchmark.QuestionAnswerPipeline.answer", side_effect=AssertionError("must not repeat")):
            second = self.run_cases()
        self.assertEqual(first, second)
        self.assertEqual(raw, (self.output / "events.jsonl").read_bytes())

    def test_failure_is_recorded_without_exception_text_and_is_not_retried(self):
        with patch("repolens.benchmark.QuestionAnswerPipeline.answer", side_effect=RuntimeError("secret-error-marker")):
            report = self.run_cases()
        self.assertEqual(report["failed"], 2)
        self.assertNotIn("secret-error-marker", (self.output / "events.jsonl").read_text())
        self.assertEqual(self.run_cases()["failed"], 2)

    def test_started_without_result_remains_uncertain_and_is_not_retried(self):
        self.run_cases()
        journal = self.output / "events.jsonl"
        journal.write_text(journal.read_text().splitlines()[0] + "\n", encoding="utf-8")
        report = self.run_cases()
        self.assertEqual(report["uncertain"], 1)
        self.assertEqual(report["completed"], 1)

    def test_budget_reservations_survive_resume(self):
        report = self.run_cases(max_calls=1)
        self.assertEqual(report["started"], 1)
        self.assertEqual(report["remaining"], 1)
        self.assertEqual(report["stop_reason"], "planned_budget_exhausted")
        self.assertEqual(report, self.run_cases(max_calls=1))
        with self.assertRaisesRegex(RepoLensError, "Frozen"):
            self.run_cases(max_calls=2)

    def test_changed_dataset_and_corrupt_journal_fail_closed(self):
        self.run_cases()
        self.cases[0]["query"] = "another question"
        self.write_dataset()
        with self.assertRaisesRegex(RepoLensError, "Frozen"):
            self.run_cases()
        self.cases[0]["query"] = "dispatch"
        self.write_dataset()
        (self.output / "events.jsonl").write_text('{"partial":', encoding="utf-8")
        with self.assertRaisesRegex(RepoLensError, "incomplete"):
            self.run_cases()

    def test_tampered_completed_output_is_rejected_on_resume(self):
        self.run_cases()
        journal = self.output / "events.jsonl"
        events = [json.loads(line) for line in journal.read_text().splitlines()]
        events[1]["output"]["summary"] = "modified output"
        journal.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")
        with self.assertRaisesRegex(RepoLensError, "output hash"):
            self.run_cases()

    def test_output_in_target_and_concurrent_runner_are_rejected(self):
        self.output = self.repo / "output"
        with self.assertRaisesRegex(RepoLensError, "outside"):
            self.run_cases()
        self.assertFalse(self.output.exists())
        self.output = self.root / "run"
        self.output.mkdir()
        (self.output / "run.lock").touch()
        with self.assertRaisesRegex(RepoLensError, "run.lock"):
            self.run_cases()
        self.assertTrue((self.output / "run.lock").exists())

    def test_symlinked_journal_cannot_write_back_into_the_target_repository(self):
        self.output.mkdir()
        target = self.repo / "untracked-journal.jsonl"
        target.write_text("", encoding="utf-8")
        journal = self.output / "events.jsonl"
        try:
            journal.symlink_to(target)
        except OSError:
            self.skipTest("Creating symlinks is unavailable on this host")
        with self.assertRaisesRegex(RepoLensError, "symbolic links"):
            self.run_cases()
        self.assertEqual(target.read_bytes(), b"")
        self.assertFalse((self.output / "run.lock").exists())
        self.assertFalse((self.output / "manifest.json").exists())

    def test_invalid_budgets_versions_and_categories_are_rejected_before_output(self):
        for options in ({"max_calls": True}, {"context_tokens": 0}, {"output_tokens": 9000}):
            with self.subTest(options=options), self.assertRaises(RepoLensError):
                self.run_cases(**options)
        self.cases[0]["commit_sha"] = "a" * 40
        self.write_dataset()
        with self.assertRaises(RepoLensError):
            self.run_cases()
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
