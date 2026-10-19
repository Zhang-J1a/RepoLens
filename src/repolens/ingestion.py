from collections import Counter
from dataclasses import replace
import os
from pathlib import Path
import time

from repolens.config import validate_data_directory
from repolens.domain import INDEX_POLICY, MAX_FILE_BYTES, MAX_TOTAL_BYTES, ParsedFile, RepoLensError, stable_id
from repolens.git import GitRepository
from repolens.index import DATABASE_NAME, IndexStore
from repolens.parsing import language_for, parse_file
from repolens.graph.schema import GRAPH_POLICY


def _resolve_snapshot(repository: str | Path, ref: str):
    git = GitRepository(repository)
    commit = git.commit(ref)
    repository_id = stable_id("repo", os.path.normcase(str(git.root)))
    snapshot_id = stable_id("snapshot", repository_id, commit.sha, INDEX_POLICY)
    return git, commit, repository_id, snapshot_id


def _validate_index_directory(git: GitRepository, directory: Path) -> Path:
    directory = directory.resolve()
    for boundary in (git.root, git.git_directory):
        validate_data_directory(directory, boundary)
        validate_data_directory((directory / DATABASE_NAME).resolve(), boundary)
    return directory


def ingest(repository: str | Path, directory: Path, ref: str = "HEAD") -> dict:
    started = time.perf_counter()
    git, commit, repository_id, snapshot_id = _resolve_snapshot(repository, ref)
    directory = _validate_index_directory(git, directory)
    previous_files = {}
    parent_snapshot_id = None
    database = directory / DATABASE_NAME
    if database.is_file() and commit.parents:
        try:
            with IndexStore(directory) as store:
                parent_snapshot_id = store.snapshot_for_commit(repository_id, commit.parents[0])
                if parent_snapshot_id is not None:
                    previous_files = store.parsed_files(parent_snapshot_id)
        except RepoLensError as exc:
            # A writable open below can migrate the previous V1 schema. In
            # that case there is no safe parsed cache to reuse yet.
            if "schema is incompatible" not in str(exc):
                raise
    previous_by_blob = {}
    for parsed in previous_files.values():
        previous_by_blob.setdefault(parsed.entry.object_id, parsed)
    files, total_bytes = [], 0
    history = git.history(commit.sha)
    branches = git.local_branches(commit.sha)
    reused_files = 0
    parsed_files = 0
    with git.blobs() as blobs:
        for entry in git.inventory(commit.sha):
            cached = previous_files.get((entry.path, entry.object_id)) or previous_by_blob.get(entry.object_id)
            if cached is not None and cached.language == language_for(entry.path) and cached.entry.mode == entry.mode:
                files.append(replace(cached, entry=entry))
                reused_files += 1
                if cached.status in ("indexed", "parse_fallback"):
                    total_bytes += entry.size
                continue
            if entry.mode == "120000":
                file = ParsedFile(entry, "symlink")
            elif entry.mode == "160000":
                file = ParsedFile(entry, "submodule")
            elif entry.mode not in ("100644", "100755"):
                file = ParsedFile(entry, "unsupported_mode")
            elif language_for(entry.path) is None:
                file = ParsedFile(entry, "unsupported_type")
            elif entry.size > MAX_FILE_BYTES:
                file = ParsedFile(entry, "too_large", language_for(entry.path))
            else:
                total_bytes += entry.size
                if total_bytes > MAX_TOTAL_BYTES:
                    raise RepoLensError("Supported source exceeds the current 64 MiB snapshot limit; indexing was stopped.")
                file = parse_file(entry, blobs.read(entry))
            files.append(file)
            parsed_files += 1
    counts = Counter(file.status for file in files)
    stats = {
        "inventory_files": len(files),
        "indexed_files": counts["indexed"] + counts["parse_fallback"],
        "symbols": sum(len(file.symbols) for file in files),
        "chunks": sum(len(file.chunks) for file in files),
        "source_bytes": total_bytes,
        "statuses": dict(sorted(counts.items())),
        "diagnostics": [
            {"path": file.entry.path, "code": file.status}
            for file in files if file.status in ("parse_fallback", "decode_error", "binary", "too_large")
        ],
        "index_mode": "incremental" if parent_snapshot_id else "full",
        "base_snapshot_id": parent_snapshot_id,
        "reused_files": reused_files,
        "parsed_files": parsed_files,
        "history_commits": len(history),
        "local_branches": branches,
    }
    with IndexStore(directory, writable=True) as store:
        store.save(git.root, repository_id, snapshot_id, commit, files, stats, history)
        result = store.snapshot(snapshot_id)
    return result | {"elapsed_seconds": round(time.perf_counter() - started, 6)}


def ingest_or_reuse(repository: str | Path, directory: Path, ref: str = "HEAD") -> dict:
    """Return an indexed snapshot, reusing an exact existing snapshot when possible."""

    git, commit, repository_id, snapshot_id = _resolve_snapshot(repository, ref)
    directory = _validate_index_directory(git, directory)
    database = directory / DATABASE_NAME
    if database.is_file():
        try:
            with IndexStore(directory) as store:
                if store.has_snapshot(snapshot_id):
                    result = store.snapshot(snapshot_id) | {
                        "elapsed_seconds": 0.0,
                        "index_action": "reused",
                    }
                    needs_graph = store.connection.execute("SELECT 1 FROM graph_builds WHERE snapshot_id=? AND policy=?", (snapshot_id, GRAPH_POLICY)).fetchone() is None
                    if not needs_graph:
                        return result
            with IndexStore(directory, writable=True) as store:
                if store.has_snapshot(snapshot_id):
                    store.ensure_graph(snapshot_id)
                    return result
        except RepoLensError as exc:
            if "schema is incompatible" not in str(exc):
                raise
    result = ingest(repository, directory, ref)
    return result | {"index_action": "created"}
