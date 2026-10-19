"""Offline V1 walkthrough using only the project's synthetic Taskboard fixture."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main() -> None:
    fixture = Path(__file__).resolve().parents[1] / "eval" / "fixtures" / "taskboard"
    with tempfile.TemporaryDirectory(prefix="repolens-demo-") as temporary:
        base = Path(temporary)
        repo, data = base / "taskboard", base / "index"
        shutil.copytree(fixture, repo, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_AUTHOR_DATE="2026-01-01T00:00:00Z", GIT_COMMITTER_DATE="2026-01-01T00:00:00Z")

        def git(*args):
            return subprocess.run(
                ["git", "-c", "init.templateDir=", "-c", "core.autocrlf=false",
                 "-c", "user.name=RepoLens Demo", "-c", "user.email=demo@example.invalid",
                 "-C", str(repo), *args], env=env, check=True, capture_output=True, timeout=30,
            ).stdout.decode("utf-8").strip()

        def cli(*args):
            result = subprocess.run([sys.executable, "-m", "repolens", *args], check=True,
                                    capture_output=True, text=True, timeout=60)
            return json.loads(result.stdout)

        git("init", "--quiet")
        git("add", "--all")
        git("commit", "--quiet", "--no-gpg-sign", "-m", "Synthetic demo fixture")
        commit = git("rev-parse", "HEAD")
        before = git("status", "--porcelain")
        environment = cli("doctor")
        snapshot = cli("ingest", str(repo), "--ref", commit, "--data-dir", str(data))
        search = cli("search", "TaskService.create_task", "--snapshot", snapshot["snapshot_id"],
                     "--data-dir", str(data), "--limit", "5")
        hits = search["results"]
        if not hits:
            raise RuntimeError("Demo retrieval returned no evidence.")
        evidence = cli("evidence", hits[0]["evidence_id"], "--snapshot", snapshot["snapshot_id"],
                       "--data-dir", str(data))
        listed = cli("snapshots", "--data-dir", str(data))
        if before != git("status", "--porcelain") or evidence["text"] != hits[0]["text"]:
            raise RuntimeError("Demo evidence or read-only check failed.")
        print(json.dumps({
            "ok": True, "version": environment["version"], "fixture": "taskboard-v0 (synthetic)",
            "commit_sha": commit, "stats": snapshot["stats"], "snapshot_count": len(listed["snapshots"]),
            "query": search["query"], "retrieval": search["retrieval"],
            "evidence": {key: evidence[key] for key in ("path", "symbol", "line_start", "line_end", "text")},
            "worktree_unchanged": True, "temporary_files_cleaned_on_exit": True,
        }, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
