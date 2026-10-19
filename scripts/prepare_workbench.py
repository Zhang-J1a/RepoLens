"""Generate V5 view data from frozen results without changing experiments."""

import hashlib
import json
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, help="Read-only frozen benchmark index for evidence-chain capture")
    args = parser.parse_args()
    evaluation = ROOT / "eval"
    cross = json.loads((evaluation / "flask-graph-v4-scope-v2-evaluation.json").read_text(encoding="utf-8"))
    runs = [("crossfile-v4", value) for value in cross["results"].values()]
    for strategy in ("vector", "hybrid", "graph"):
        path = evaluation / f"flask-graph-v4-validation-scope-v2-{strategy}.json"
        runs.append(("validation-v4", json.loads(path.read_text(encoding="utf-8"))))
    result = []
    for group, record in runs:
        run = record["run"]
        dataset = (evaluation / run["dataset"]).read_bytes()
        if hashlib.sha256(dataset).hexdigest() != run["dataset_sha256"]:
            raise ValueError("Frozen dataset hash mismatch")
        gold = {item["id"]: item for item in [json.loads(line) for line in dataset.decode().splitlines() if line.strip()]}
        cases = [case | {"query": gold[case["id"]]["query"],
                         "expected_evidence": gold[case["id"]]["expected_evidence"]}
                 for case in record["cases"]]
        if args.index:
            from repolens.evaluation import _score_case
            from repolens.index import IndexStore
            methods = {"vector": "search_vector", "hybrid": "search_hybrid", "graph": "search_graph"}
            with IndexStore(args.index) as store:
                for case in cases:
                    hits = getattr(store, methods[run["strategy"]])(case["query"], run["snapshot_id"], limit=10)
                    scores = _score_case(gold[case["id"]], hits)
                    if any(abs(scores[key] - case[key]) > 1e-12 for key in scores):
                        raise ValueError(f"Frozen retrieval changed: {group}/{run['strategy']}/{case['id']}")
                    case["retrieved_evidence"] = [{key: value for key, value in hit.items() if key in (
                        "evidence_id", "snapshot_id", "commit_sha", "path", "symbol", "kind", "line_start", "line_end",
                        "bm25_score", "vector_score", "hybrid_score", "graph_score", "retrieval_method")}
                        for hit in hits]
        result.append({"id": group + "-" + run["strategy"], "group": group, "run": run,
                       "metrics": record["metrics"], "by_category": record["by_category"],
                       "cases": cases,
                       "citation_precision": None, "answer_accuracy": None,
                       "source_sha256": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()})
    target = ROOT / "src/repolens/workbench/fixtures/evaluations.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {"purpose": "V5 view-only supplement; frozen experiments remain unchanged",
                "view_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                "replayed_cases": sum(len(run["cases"]) for run in result) if args.index else 0,
                "nonempty_retrieval_cases": sum(bool(case.get("retrieved_evidence")) for run in result for case in run["cases"]),
                "source_files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (
                    evaluation / "flask-graph-v4-scope-v2-evaluation.json",
                    *(evaluation / f"flask-graph-v4-validation-scope-v2-{strategy}.json" for strategy in ("vector", "hybrid", "graph")))}}
    (evaluation / "v5-workbench-view-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(result)} frozen evaluation views")


if __name__ == "__main__":
    main()
