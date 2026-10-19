"""Freeze input/implementation before comparing retrieval strategies on a fixed repository."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from repolens.evaluation import evaluate_dataset
from repolens.graph.query import GraphStore
from repolens.graph.schema import GRAPH_POLICY, GRAPH_RETRIEVAL_POLICY
from repolens.index import IndexStore
from repolens.ingestion import ingest_or_reuse


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    implementation = {str(path.relative_to(root)).replace("\\", "/"): file_hash(path)
                      for path in sorted((root / "src/repolens/graph").glob("*.py"))}
    for relative in ("src/repolens/index.py", "src/repolens/embeddings.py", "src/repolens/retrieval.py",
                     "src/repolens/evaluation.py", "scripts/graph_benchmark.py"):
        implementation[relative] = file_hash(root / relative)
    frozen = {"dataset_sha256": file_hash(Path(args.dataset)), "implementation_sha256": implementation,
              "graph_policy": GRAPH_POLICY, "retrieval_policy": GRAPH_RETRIEVAL_POLICY,
              "primary_acceptance": "graph cross-file macro Recall@10 greater than pure vector; report all regressions"}
    manifest = Path(args.manifest)
    if manifest.exists():
        previous = json.loads(manifest.read_text(encoding="utf-8"))
        if any(previous[key] != value for key, value in frozen.items()):
            raise RuntimeError("Frozen inputs or implementation changed; use a new documented experiment manifest.")
    else:
        manifest.write_text(json.dumps(frozen | {"frozen_before_first_retrieval_utc": datetime.now(timezone.utc).isoformat()},
                                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    snapshot = ingest_or_reuse(args.repository, Path(args.data_dir), args.ref)
    with IndexStore(Path(args.data_dir)) as store:
        results = {strategy: evaluate_dataset(args.dataset, store, snapshot["snapshot_id"], strategy=strategy)
                   for strategy in ("vector", "hybrid", "graph")}
        info = GraphStore(store).info(snapshot["snapshot_id"])
    comparisons = []
    for vector, graph in zip(results["vector"]["cases"], results["graph"]["cases"]):
        comparisons.append({"id": vector["id"], "vector_recall@10": vector["recall@10"],
                            "graph_recall@10": graph["recall@10"], "delta": graph["recall@10"] - vector["recall@10"]})
    report = {"schema_version": "repolens.graph-benchmark.v1", "manifest_sha256": file_hash(manifest),
              "graph": info, "results": results, "paired_recall@10": comparisons,
              "acceptance_gain": results["graph"]["metrics"]["recall@10"] > results["vector"]["metrics"]["recall@10"],
              "limitations": "Ten authored cross-file cases on one Flask commit; no external blind test or real model evaluation."}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"output": args.output, "sha256": file_hash(Path(args.output)), "graph": info,
                      "acceptance_gain": report["acceptance_gain"],
                      "metrics": {key: value["metrics"] for key, value in results.items()}}, indent=2))


if __name__ == "__main__":
    main()
