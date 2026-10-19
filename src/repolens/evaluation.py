"""Offline retrieval evaluation against snapshot-scoped evidence locators."""

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import re
import sqlite3
import time

from repolens import __version__
from repolens.domain import RepoLensError, source_lines
from repolens.git import safe_repository_path
from repolens.index import (
    FTS_BM25_WEIGHTS,
    FTS_CANDIDATE_LIMIT,
    FTS_QUERY_POLICY,
    KEYWORD_RETRIEVAL_POLICY,
    RETRIEVAL_POLICY,
    VECTOR_RETRIEVAL_POLICY,
    IndexStore,
)
from repolens.retrieval import RERANK_COVERAGE_WEIGHT, RERANK_SYMBOL_ROOT_WEIGHT
from repolens.graph.schema import GRAPH_RETRIEVAL_POLICY


METRIC_CUTOFFS = (5, 10)
METRIC_KEYS = ("recall@5", "recall@10", "mrr", "ndcg@10")
_FULL_SHA = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def _read_dataset(path: Path) -> tuple[list[dict], str]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RepoLensError("Could not read the evaluation dataset as UTF-8 JSONL.") from exc

    cases = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RepoLensError(f"Evaluation dataset line {line_number} is not valid JSON.") from exc
        if not isinstance(case, dict):
            raise RepoLensError(f"Evaluation dataset line {line_number} must contain a JSON object.")
        cases.append(case)
    if not cases:
        raise RepoLensError("Evaluation dataset contains no cases.")
    return cases, hashlib.sha256(raw).hexdigest()


def _validate_cases(cases: list[dict], store: IndexStore, snapshot_id: str) -> tuple[list[dict], dict]:
    snapshot = store.snapshot(snapshot_id)
    case_ids = set()
    repositories = set()
    commits = set()
    normalized = []

    for case_number, case in enumerate(cases, 1):
        required = ("id", "repo", "commit_sha", "category", "query", "expected_behavior", "expected_evidence")
        if any(key not in case for key in required):
            raise RepoLensError(f"Evaluation case {case_number} is missing a required field.")
        if any(not isinstance(case[key], str) or not case[key].strip() for key in required[:-1]):
            raise RepoLensError(f"Evaluation case {case_number} has an empty or invalid text field.")
        if case["id"] in case_ids:
            raise RepoLensError(f"Evaluation dataset contains duplicate case ID {case['id']!r}.")
        case_ids.add(case["id"])
        repositories.add(case["repo"])
        commits.add(case["commit_sha"])
        if not _FULL_SHA.fullmatch(case["commit_sha"]):
            raise RepoLensError(f"Evaluation case {case['id']!r} must use a full lowercase commit SHA.")
        if case["commit_sha"] != snapshot["commit_sha"]:
            raise RepoLensError(
                f"Dataset commit {case['commit_sha']} does not match "
                f"selected snapshot commit {snapshot['commit_sha']}."
            )
        if not isinstance(case["expected_evidence"], list) or not case["expected_evidence"]:
            raise RepoLensError(f"Evaluation case {case['id']!r} must have at least one evidence locator.")

        gold = []
        seen_locators = set()
        for locator_number, locator in enumerate(case["expected_evidence"], 1):
            if not isinstance(locator, dict):
                raise RepoLensError(f"Case {case['id']!r} evidence {locator_number} must be an object.")
            path = locator.get("path")
            start = locator.get("line_start")
            end = locator.get("line_end")
            symbol = locator.get("symbol")
            if not isinstance(path, str) or not safe_repository_path(path):
                raise RepoLensError(f"Case {case['id']!r} has an unsafe or invalid evidence path.")
            if type(start) is not int or type(end) is not int or start < 1 or end < start:
                raise RepoLensError(f"Case {case['id']!r} has an invalid 1-based inclusive line range.")
            if symbol is not None and (not isinstance(symbol, str) or not symbol.strip()):
                raise RepoLensError(f"Case {case['id']!r} has an invalid evidence symbol.")
            identity = (path, start, end, symbol)
            if identity in seen_locators:
                raise RepoLensError(f"Case {case['id']!r} repeats an evidence locator.")
            seen_locators.add(identity)

            file = store.connection.execute(
                """SELECT id, text FROM files WHERE snapshot_id=? AND path=?
                   AND status IN ('indexed', 'parse_fallback')""",
                (snapshot_id, path),
            ).fetchone()
            if file is None or file["text"] is None:
                raise RepoLensError(f"Case {case['id']!r} evidence path {path!r} is not indexed in this snapshot.")
            lines = source_lines(file["text"])
            if end > len(lines):
                raise RepoLensError(f"Case {case['id']!r} evidence range exceeds {path!r} ({len(lines)} lines).")

            if symbol is None:
                chunk = store.connection.execute(
                    """SELECT 1 FROM chunks WHERE snapshot_id=? AND file_id=?
                       AND line_start<=? AND line_end>=? LIMIT 1""",
                    (snapshot_id, file["id"], end, start),
                ).fetchone()
            else:
                symbol_rows = store.connection.execute(
                    "SELECT line_start, line_end FROM symbols WHERE file_id=? AND name=?",
                    (file["id"], symbol),
                ).fetchall()
                if not symbol_rows:
                    raise RepoLensError(f"Case {case['id']!r} symbol {symbol!r} does not exist in {path!r}.")
                if not any(row["line_start"] <= start <= end <= row["line_end"] for row in symbol_rows):
                    raise RepoLensError(
                        f"Case {case['id']!r} evidence range is outside symbol {symbol!r}."
                    )
                chunk = store.connection.execute(
                    """SELECT 1 FROM chunks WHERE snapshot_id=? AND file_id=? AND symbol=?
                       AND line_start<=? AND line_end>=? LIMIT 1""",
                    (snapshot_id, file["id"], symbol, end, start),
                ).fetchone()
            if chunk is None:
                raise RepoLensError(f"Case {case['id']!r} evidence range is not retrievable from the index.")
            gold.append({"path": path, "line_start": start, "line_end": end, "symbol": symbol})

        normalized.append(case | {"expected_evidence": gold})

    if len(repositories) != 1 or len(commits) != 1:
        raise RepoLensError("An evaluation dataset must target exactly one repository and one commit.")
    return normalized, snapshot


def _matches(result: dict, locator: dict) -> bool:
    if result["path"] != locator["path"]:
        return False
    if locator["symbol"] is not None and result["symbol"] != locator["symbol"]:
        return False
    return result["line_start"] <= locator["line_end"] and result["line_end"] >= locator["line_start"]


def _score_case(case: dict, results: list[dict]) -> dict:
    gold = case["expected_evidence"]
    covered = {cutoff: set() for cutoff in METRIC_CUTOFFS}
    seen_results = set()
    reciprocal_rank = 0.0
    dcg = 0.0

    for rank, result in enumerate(results, 1):
        identity = result.get("evidence_id") or (
            result["path"], result["symbol"], result["line_start"], result["line_end"], result["text"]
        )
        if identity in seen_results:
            continue
        seen_results.add(identity)
        matched = {index for index, locator in enumerate(gold) if _matches(result, locator)}
        new_matches = matched - covered[10]
        if not new_matches:
            continue
        if reciprocal_rank == 0.0:
            reciprocal_rank = 1.0 / rank
        if rank <= 10:
            dcg += 1.0 / math.log2(rank + 1)
        for cutoff in METRIC_CUTOFFS:
            if rank <= cutoff:
                covered[cutoff].update(new_matches)

    ideal_count = min(10, len(gold))
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return {
        "recall@5": len(covered[5]) / len(gold),
        "recall@10": len(covered[10]) / len(gold),
        "mrr": reciprocal_rank,
        "ndcg@10": dcg / idcg if idcg else 0.0,
        "evidence_covered@5": len(covered[5]),
        "evidence_covered@10": len(covered[10]),
    }


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _aggregate(cases: list[dict], latencies: list[float]) -> dict:
    count = len(cases)
    metrics = {
        key: sum(case[key] for case in cases) / count
        for key in METRIC_KEYS
    }
    errors = sum("error" in case for case in cases)
    return metrics | {
        "case_count": count,
        "query_error_count": errors,
        "query_error_rate": errors / count,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "mean": sum(latencies) / len(latencies),
        },
    }


def evaluate_dataset(
    dataset_path: str | Path, store: IndexStore, snapshot_id: str, *, limit: int = 10,
    strategy: str = "keyword",
) -> dict:
    """Validate gold evidence against one snapshot, then score one retrieval path."""
    started_at_utc = datetime.now(timezone.utc).isoformat()
    if not 10 <= limit <= 100:
        raise RepoLensError("Evaluation search limit must be between 10 and 100.")
    if strategy not in ("keyword", "vector", "hybrid", "graph"):
        raise RepoLensError("Evaluation retrieval strategy must be keyword, vector, hybrid, or graph.")
    search_method = {
        "keyword": store.search,
        "vector": store.search_vector,
        "hybrid": store.search_hybrid,
        "graph": store.search_graph,
    }[strategy]
    path = Path(dataset_path)
    cases, dataset_sha256 = _read_dataset(path)
    cases, snapshot = _validate_cases(cases, store, snapshot_id)

    case_results = []
    latencies = []
    for case in cases:
        started = time.perf_counter()
        error = None
        try:
            results = search_method(case["query"], snapshot_id, limit=limit)
        except RepoLensError as exc:
            results = []
            error = str(exc)
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies.append(elapsed_ms)
        score = _score_case(case, results)
        case_result = {
            "id": case["id"],
            "category": case["category"],
            "gold_evidence_count": len(case["expected_evidence"]),
            "retrieved_count": len(results),
            "latency_ms": elapsed_ms,
        } | score
        if error is not None:
            case_result["error"] = error
        case_results.append(case_result)

    grouped = defaultdict(list)
    grouped_latencies = defaultdict(list)
    for case in case_results:
        grouped[case["category"]].append(case)
        grouped_latencies[case["category"]].append(case["latency_ms"])

    categories = {
        category: _aggregate(group, grouped_latencies[category])
        for category, group in sorted(grouped.items())
    }
    corpus = store.connection.execute(
        "SELECT id, repository_id, commit_sha, policy FROM snapshots ORDER BY id"
    ).fetchall()
    return {
        "schema_version": 1,
        "run": {
            "started_at_utc": started_at_utc,
            "dataset": path.name,
            "dataset_sha256": dataset_sha256,
            "repository": cases[0]["repo"],
            "commit_sha": snapshot["commit_sha"],
            "snapshot_id": snapshot_id,
            "index_policy": snapshot["policy"],
            "retrieval": {
                "keyword": KEYWORD_RETRIEVAL_POLICY,
                "vector": VECTOR_RETRIEVAL_POLICY,
                "hybrid": RETRIEVAL_POLICY,
                "graph": GRAPH_RETRIEVAL_POLICY,
            }[strategy],
            "strategy": strategy,
            "query_policy": FTS_QUERY_POLICY,
            "bm25_weights": dict(zip(("path", "symbol", "text"), FTS_BM25_WEIGHTS)),
            "candidate_limit": FTS_CANDIDATE_LIMIT,
            "candidate_policy": "vector-100-plus-bounded-static-graph" if strategy == "graph" else "fixed-100",
            "graph_expansion": ({"max_seed_nodes": 8, "fallback_vector_seeds": 5, "hops": 2,
                                 "max_nodes": 120, "max_edges": 300, "chunks_per_node": 2,
                                 "vector_weight": 0.4, "graph_weight": 0.6, "exact_seed_weight": 1.0,
                                 "rrf_offset": 60} if strategy == "graph" else None),
            "rerank_weights": {
                "identifier_coverage": RERANK_COVERAGE_WEIGHT,
                "symbol_root": RERANK_SYMBOL_ROOT_WEIGHT,
            },
            "top_k": limit,
            "metric_cutoffs": list(METRIC_CUTOFFS),
            "validated_evidence_count": sum(len(case["expected_evidence"]) for case in cases),
            "snapshot_stats": snapshot["stats"],
            "index_corpus": [dict(row) for row in corpus],
            "environment": {
                "repolens_version": __version__,
                "python": platform.python_version(),
                "sqlite": sqlite3.sqlite_version,
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
            },
        },
        "metrics": _aggregate(case_results, latencies),
        "by_category": categories,
        "cases": case_results,
    }
