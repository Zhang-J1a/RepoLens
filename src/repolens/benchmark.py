"""Offline generation benchmark preparation with frozen inputs and a durable journal."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from repolens.config import validate_data_directory
from repolens.context import EvidenceContextPacker
from repolens.domain import RepoLensError
from repolens.evaluation import _read_dataset
from repolens.generation_evaluation import output_hash
from repolens.git import GitRepository
from repolens.index import IndexStore
from repolens.pipeline import QuestionAnswerPipeline
from repolens.provider import MockProvider


STRATEGIES = ("keyword", "vector", "hybrid", "graph")


def _append(path: Path, value: dict) -> None:
    import os

    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=True, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_benchmark(dataset, directory, snapshot_id, output_directory, *,
                  strategies=STRATEGIES, max_calls=32, max_planned_tokens=200000,
                  context_tokens=2400, output_tokens=768) -> dict:
    """Run only Mock; reserve before each case and never retry uncertain attempts."""
    for name, value, upper in (("max_calls", max_calls, 10000),
                               ("max_planned_tokens", max_planned_tokens, 100000000),
                               ("context_tokens", context_tokens, 16000),
                               ("output_tokens", output_tokens, 8192)):
        if type(value) is not int or not 1 <= value <= upper:
            raise RepoLensError(f"Benchmark {name} must be an integer in 1..{upper}.")
    strategies = tuple(strategies)
    if not strategies or any(item not in STRATEGIES for item in strategies) or len(set(strategies)) != len(strategies):
        raise RepoLensError("Benchmark strategies must be distinct supported retrieval paths.")
    cases, dataset_hash = _read_dataset(Path(dataset))
    if len(cases) > 2000:
        raise RepoLensError("Benchmark dataset exceeds 2000 cases.")
    seen = set()
    with IndexStore(Path(directory)) as store:
        snapshot = store.snapshot(snapshot_id)
        for case in cases:
            if not isinstance(case.get("id"), str) or not 1 <= len(case["id"].strip()) <= 128:
                raise RepoLensError("Benchmark case requires a stable ID of 1..128 characters.")
            if case["id"] in seen:
                raise RepoLensError("Benchmark case IDs must be unique.")
            seen.add(case["id"])
            if (not isinstance(case.get("query"), str) or not case["query"].strip()
                    or not 1 <= len(case["query"]) <= 4096):
                raise RepoLensError("Benchmark query must contain 1..4096 characters.")
            if case.get("commit_sha") != snapshot["commit_sha"] or type(case.get("answerable")) is not bool:
                raise RepoLensError("Benchmark case commit/answerability must match the fixed snapshot.")
            if not isinstance(case.get("category"), str) or not case["category"].strip():
                raise RepoLensError("Benchmark case requires a category.")
        git = GitRepository(snapshot["root"])
        target = Path(output_directory).resolve()
        validate_data_directory(target, git.root)
        validate_data_directory(target, git.git_directory)
        corpus = [dict(row) for row in store.connection.execute(
            "SELECT id, repository_id, commit_sha, policy FROM snapshots ORDER BY id"
        )]
        source = Path(__file__).parent
        implementation = {path.relative_to(source).as_posix(): hashlib.sha256(
            path.read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest() for path in sorted(source.rglob("*.py")) if "fixtures" not in path.parts}
        expected = {
            "schema_version": "repolens.generation-benchmark.v1",
            "scope": "offline-mock-contract-not-model-quality", "provider": "mock",
            "model": "mock-deterministic-v1", "dataset_sha256": dataset_hash,
            "snapshot_id": snapshot_id, "commit_sha": snapshot["commit_sha"],
            "index_policy": snapshot["policy"], "index_corpus": corpus,
            "implementation_sha256_lf": implementation, "strategies": list(strategies),
            "top_k": 5, "follow_up_searches": 0, "max_calls": max_calls,
            "max_planned_tokens": max_planned_tokens, "context_tokens": context_tokens,
            "output_tokens": output_tokens, "case_count": len(cases),
            "full_context": {"status": "unavailable", "reason": "No authorized real-model comparison in offline runner."},
        }
        target.mkdir(parents=True, exist_ok=True)
        lock = target / "run.lock"
        try:
            lock_stream = lock.open("x", encoding="utf-8")
        except FileExistsError:
            raise RepoLensError("Benchmark run.lock exists; verify no runner is active before recovery.") from None
        try:
            lock_stream.close()
            manifest = target / "manifest.json"
            if manifest.exists():
                try:
                    previous = json.loads(manifest.read_text(encoding="utf-8"))
                except (OSError, ValueError) as exc:
                    raise RepoLensError("Benchmark manifest is unreadable.") from exc
                if not isinstance(previous, dict) or {key: value for key, value in previous.items()
                                                     if key != "frozen_at_utc"} != expected:
                    raise RepoLensError("Frozen benchmark inputs changed; use a new output directory.")
            else:
                with manifest.open("x", encoding="utf-8", newline="\n") as stream:
                    json.dump(expected | {"frozen_at_utc": datetime.now(timezone.utc).isoformat()},
                              stream, ensure_ascii=True, indent=2)
                    stream.write("\n")
            manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
            journal = target / "events.jsonl"
            events = []
            if journal.exists():
                try:
                    events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
                except (OSError, ValueError) as exc:
                    raise RepoLensError("Benchmark journal is incomplete; preserve it for manual recovery.") from exc
            tasks = {(strategy, case["id"]): case for strategy in strategies for case in cases}
            started, terminal = {}, {}
            for event in events:
                if not isinstance(event, dict) or event.get("manifest_sha256") != manifest_hash:
                    raise RepoLensError("Benchmark event does not match the frozen manifest.")
                if not isinstance(event.get("strategy"), str) or not isinstance(event.get("id"), str):
                    raise RepoLensError("Benchmark event identity is invalid.")
                identity = (event.get("strategy"), event.get("id"))
                if identity not in tasks:
                    raise RepoLensError("Benchmark journal contains an unknown case.")
                if event.get("status") == "started" and identity not in started:
                    reservation = event.get("planned_tokens")
                    if type(reservation) is not int or reservation != context_tokens + output_tokens + 2048:
                        raise RepoLensError("Benchmark journal has an invalid reservation.")
                    started[identity] = event
                elif event.get("status") in ("completed", "failed") and identity in started and identity not in terminal:
                    if event["status"] == "completed":
                        if not isinstance(event.get("output"), dict) or event.get("output_sha256") != output_hash(event["output"]):
                            raise RepoLensError("Benchmark saved output hash does not match its journal.")
                    terminal[identity] = event
                else:
                    raise RepoLensError("Benchmark journal event order is invalid.")
            reserved_tokens = sum(event["planned_tokens"] for event in started.values())
            if len(started) > max_calls or reserved_tokens > max_planned_tokens:
                raise RepoLensError("Benchmark journal exceeds its frozen budget.")
            stop_reason = None
            for identity, case in tasks.items():
                if identity in started:
                    continue
                reservation = context_tokens + output_tokens + 2048
                if len(started) >= max_calls or reserved_tokens + reservation > max_planned_tokens:
                    stop_reason = "planned_budget_exhausted"
                    break
                strategy, case_id = identity
                common = {"id": case_id, "strategy": strategy, "manifest_sha256": manifest_hash}
                event = common | {"status": "started", "planned_tokens": reservation}
                _append(journal, event)
                started[identity] = event
                reserved_tokens += reservation
                try:
                    result = QuestionAnswerPipeline(
                        store, snapshot_id, MockProvider(), retrieval_strategy=strategy,
                        context_packer=EvidenceContextPacker(context_tokens), max_output_tokens=output_tokens,
                    ).answer(case["query"], limit=5)
                    answer = result.answer.to_dict()
                    output = {key: answer[key] for key in ("status", "summary", "claims", "unknowns")}
                    event = common | {
                        "status": "completed", "answerable": case["answerable"], "category": case["category"],
                        "output": output, "output_sha256": output_hash(output),
                        "canonical_citations": answer["citations"], "context": result.context.to_dict(),
                        "telemetry": result.telemetry.to_dict(),
                    }
                except Exception:
                    event = common | {"status": "failed", "error_code": "case_failed"}
                _append(journal, event)
                terminal[identity] = event
            return {
                "scope": expected["scope"], "manifest_sha256": manifest_hash,
                "started": len(started), "completed": sum(item["status"] == "completed" for item in terminal.values()),
                "failed": sum(item["status"] == "failed" for item in terminal.values()),
                "uncertain": len(started) - len(terminal), "remaining": len(tasks) - len(started),
                "reserved_planned_tokens": reserved_tokens, "stop_reason": stop_reason,
                "actual_billed_tokens": None, "cost": None, "full_context": expected["full_context"],
            }
        finally:
            lock.unlink()
