"""Reproduce frozen retrieval scores and audit a bounded identifier RRF experiment.

Run from the project root with PYTHONPATH=src. This consumes the same internal
scorer as evaluate, but neither changes the dataset nor the default retriever.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys

from repolens.domain import RepoLensError
from repolens.evaluation import METRIC_KEYS, _matches, _read_dataset, _score_case, _validate_cases
from repolens.index import FTS_BM25_WEIGHTS, FTS_CANDIDATE_LIMIT, IndexStore, match_expression
from repolens.retrieval import identifier_terms, rerank_candidates


EXPERIMENT_POLICY = "identifier-phrases-rrf-v1"
MAX_SUBQUERIES = 3
RRF_K = 60
TOP_K = 10


def legacy_expression(query: str) -> str:
    """Frozen V1.2 literal-term expression, without V1.3 phrase expansion."""
    terms = list(dict.fromkeys(re.findall(r"[^\W_]+", query, re.UNICODE)))
    if not terms or len(query) > 4096 or len(terms) > 64:
        raise RepoLensError("Query is outside the V1.2 expression limits.")
    return " OR ".join('"' + term + '"' for term in terms)


def identifier_subqueries(query: str) -> list[str]:
    match_expression(query)
    phrases = []
    for term in identifier_terms(query):
        term = term.strip(".")
        if "_" not in term and "." not in term:
            continue
        # Qualified name and method name can find different implementations.
        for phrase in (term, term.rsplit(".", 1)[-1]):
            if phrase and phrase not in phrases:
                phrases.append(phrase)
    return ['"' + phrase + '"' for phrase in phrases[:MAX_SUBQUERIES]]


def fts_candidates(store: IndexStore, snapshot_id: str, expression: str) -> list[dict]:
    store.snapshot(snapshot_id)
    rows = store.connection.execute(
        """SELECT c.id, c.path, c.symbol, c.line_start, c.line_end, c.text,
                  bm25(chunks_fts, ?, ?, ?) AS bm25_score
           FROM chunks_fts JOIN chunks c ON c.rowid=chunks_fts.rowid
           WHERE chunks_fts MATCH ? AND c.snapshot_id=?
           ORDER BY bm25_score, c.path, c.line_start, c.id LIMIT ?""",
        (*FTS_BM25_WEIGHTS, expression, snapshot_id, FTS_CANDIDATE_LIMIT),
    ).fetchall()
    return [dict(row) for row in rows]


def reciprocal_rank_fusion(rankings: list[list[dict]]) -> list[dict]:
    scores, records, first_rank = {}, {}, {}
    for ranking in rankings:
        seen = set()
        for rank, row in enumerate(ranking, 1):
            identity = row["id"]
            if identity in seen:
                continue
            seen.add(identity)
            records[identity] = row
            first_rank.setdefault(identity, rank)
            scores[identity] = scores.get(identity, 0.0) + 1.0 / (RRF_K + rank)
    ordered = sorted(records, key=lambda identity: (
        -scores[identity], first_rank[identity], records[identity]["path"],
        records[identity]["line_start"], identity,
    ))
    return [records[identity] | {"rrf_score": scores[identity]} for identity in ordered]


def compact(row: dict) -> dict:
    return {key: row[key] for key in ("id", "path", "symbol", "line_start", "line_end")}


def first_gold_rank(locator: dict, ranking: list[dict]) -> int | None:
    return next((rank for rank, row in enumerate(ranking, 1) if _matches(row, locator)), None)


def verify_scores(actual: list[dict], frozen: dict) -> None:
    expected = {row["id"]: row for row in frozen["cases"]}
    if len(expected) != len(frozen["cases"]) or set(expected) != {row["id"] for row in actual}:
        raise RepoLensError("Frozen report case IDs do not match the dataset.")
    for row in actual:
        for metric in (*METRIC_KEYS, "evidence_covered@5", "evidence_covered@10"):
            if not math.isclose(row[metric], expected[row["id"]][metric], abs_tol=1e-12, rel_tol=0):
                raise RepoLensError(f"Frozen score mismatch: {row['id']} / {metric}.")
    for metric in METRIC_KEYS:
        mean = sum(row[metric] for row in actual) / len(actual)
        if not math.isclose(mean, frozen["metrics"][metric], abs_tol=1e-12, rel_tol=0):
            raise RepoLensError(f"Frozen aggregate mismatch: {metric}.")


def compare_cases(before: list[dict], after: list[dict]) -> dict:
    old = {row["id"]: row for row in before}
    summary = {}
    for metric in METRIC_KEYS:
        groups = {"improved": [], "regressed": [], "unchanged": []}
        for row in after:
            delta = row[metric] - old[row["id"]][metric]
            label = "unchanged" if abs(delta) < 1e-12 else "improved" if delta > 0 else "regressed"
            groups[label].append(row["id"])
        summary[metric] = groups
    return summary


def run_review(dataset: Path, store: IndexStore, snapshot_id: str,
               baseline_paths: dict[str, Path]) -> dict:
    cases, dataset_sha = _read_dataset(dataset)
    cases, snapshot = _validate_cases(cases, store, snapshot_id)
    corpus = [dict(row) for row in store.connection.execute(
        "SELECT id, repository_id, commit_sha, policy FROM snapshots ORDER BY id"
    )]
    frozen = {name: json.loads(path.read_text(encoding="utf-8-sig"))
              for name, path in baseline_paths.items()}
    for report in frozen.values():
        expected = {
            "dataset_sha256": dataset_sha, "commit_sha": snapshot["commit_sha"],
            "snapshot_id": snapshot_id, "index_policy": snapshot["policy"],
            "top_k": TOP_K, "index_corpus": corpus, "snapshot_stats": snapshot["stats"],
        }
        for key, value in expected.items():
            if report["run"].get(key) != value:
                raise RepoLensError(f"Frozen report metadata mismatch: {key}.")

    all_scores = {name: [] for name in ("v1.2", "v1.3", EXPERIMENT_POLICY)}
    diagnostics, query_counts = [], Counter()
    for case in cases:
        query = case["query"]
        old = fts_candidates(store, snapshot_id, legacy_expression(query))
        raw = fts_candidates(store, snapshot_id, match_expression(query))
        current = rerank_candidates(raw, query, FTS_CANDIDATE_LIMIT)
        actual = store.search(query, snapshot_id, limit=TOP_K)
        if [row["id"] for row in current[:TOP_K]] != [row["evidence_id"] for row in actual]:
            raise RepoLensError(f"Current search replay mismatch: {case['id']}.")
        subqueries = identifier_subqueries(query)
        extra = [fts_candidates(store, snapshot_id, expression) for expression in subqueries]
        fused = reciprocal_rank_fusion([current, *extra]) if subqueries else current
        query_counts[1 + len(subqueries)] += 1
        rankings = {"v1.2": old, "v1.3_candidates": raw, "v1.3": current, EXPERIMENT_POLICY: fused}
        scores = {}
        for name in all_scores:
            # Resolve every result used for scoring through the normal evidence check.
            results = [store.evidence(row["id"], snapshot_id) for row in rankings[name][:TOP_K]]
            scores[name] = _score_case(case, results)
            all_scores[name].append({"id": case["id"], "category": case["category"], **scores[name]})
        diagnostics.append({
            "id": case["id"], "category": case["category"], "query": query,
            "subqueries": subqueries, "metrics": scores,
            "gold": [locator | {
                "first_ranks": {name: first_gold_rank(locator, ranking) for name, ranking in rankings.items()}
            } for locator in case["expected_evidence"]],
            "top10": {name: [compact(row) for row in ranking[:TOP_K]] for name, ranking in rankings.items()},
        })
    for name, report in frozen.items():
        verify_scores(all_scores[name], report)

    metrics = {name: {key: sum(row[key] for row in rows) / len(rows) for key in METRIC_KEYS}
               for name, rows in all_scores.items()}
    new_zero_hits = [case["id"] for case in diagnostics
                    if case["metrics"]["v1.3"]["recall@10"] > 0
                    and case["metrics"][EXPERIMENT_POLICY]["recall@10"] == 0]
    gate_passed = (
        metrics[EXPERIMENT_POLICY]["recall@10"] > metrics["v1.3"]["recall@10"]
        and all(metrics[EXPERIMENT_POLICY][key] >= metrics["v1.3"][key] for key in METRIC_KEYS)
        and not new_zero_hits
    )
    root = Path(__file__).resolve().parents[1]
    return {
        "schema_version": 1,
        "run": {
            "created_at_utc": datetime.now(timezone.utc).isoformat(), "dataset_sha256": dataset_sha,
            "commit_sha": snapshot["commit_sha"], "snapshot_id": snapshot_id,
            "index_policy": snapshot["policy"], "index_corpus": corpus,
            "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
            "baseline_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for name, path in baseline_paths.items()},
            "source_sha256": {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in (
                "experiments/retrieval_review.py", "src/repolens/index.py",
                "src/repolens/retrieval.py", "src/repolens/evaluation.py",
            )},
            "top_k": TOP_K, "case_count": len(cases), "validated_locators": sum(
                len(case["expected_evidence"]) for case in cases),
            "frozen_scores_reproduced": True,
        },
        "experiment": {
            "policy": EXPERIMENT_POLICY, "max_subqueries": MAX_SUBQUERIES, "rrf_k": RRF_K,
            "candidate_limit_per_query": FTS_CANDIDATE_LIMIT, "route_weights": "equal",
            "fts_query_count_distribution": dict(sorted(query_counts.items())),
            "latency_measured": False, "default_changed": False,
            "development_gate_passed": gate_passed, "new_zero_hit_cases": new_zero_hits,
            "gate": "Recall@10 increases; all four macro metrics do not decrease; no new zero-hit cases.",
        },
        "metrics": metrics,
        "v1.2_to_v1.3": compare_cases(all_scores["v1.2"], all_scores["v1.3"]),
        "v1.3_to_experiment": compare_cases(all_scores["v1.3"], all_scores[EXPERIMENT_POLICY]),
        "by_category": {category: {
            name: {key: sum(row[key] for row in rows if row["category"] == category) / sum(
                row["category"] == category for row in rows) for key in METRIC_KEYS}
            for name, rows in all_scores.items()
        } for category in sorted({case["category"] for case in cases})},
        "cases": diagnostics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--v12", type=Path, required=True)
    parser.add_argument("--v13", type=Path, required=True)
    args = parser.parse_args()
    try:
        with IndexStore(args.data_dir) as store:
            report = run_review(args.dataset, store, args.snapshot, {"v1.2": args.v12, "v1.3": args.v13})
        print(json.dumps(report, ensure_ascii=True, indent=2))
    except (RepoLensError, OSError, sqlite3.Error, ValueError, KeyError, TypeError) as exc:
        detail = str(exc) if isinstance(exc, RepoLensError) else "Check dataset, baseline JSON, and index inputs."
        print(f"Retrieval review failed: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
