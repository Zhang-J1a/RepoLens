"""V6 offline regression gate for frozen retrieval artifacts.

Without --index this validates provenance, frozen view hashes, and the explicit
"not measured" generation metrics. With --index it replays vector/hybrid/graph
retrieval against the selected snapshot and compares every recorded metric.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "eval"
VIEW = ROOT / "src" / "repolens" / "workbench" / "fixtures" / "evaluations.json"
MANIFEST = EVAL / "v5-workbench-view-manifest.json"
POLICY = EVAL / "v6-policy-manifest.json"
LANGCHAIN_POLICY = EVAL / "v6-langchain-policy-manifest.json"
PROVIDER_MODEL_POLICY = EVAL / "v6-provider-model-policy-manifest.json"
AGENT_PATH_POLICY = EVAL / "v6-agent-path-policy-manifest.json"
POLICY_FILES = ("src/repolens/domain.py", "src/repolens/parsing.py", "src/repolens/embeddings.py",
                "src/repolens/retrieval.py", "src/repolens/provider.py", "src/repolens/context.py",
                "src/repolens/answer.py", "src/repolens/pipeline.py", "src/repolens/agent/runner.py",
                "src/repolens/agent/tools.py")
LANGCHAIN_POLICY_FILES = ("src/repolens/pipeline.py", "src/repolens/langchain_integration.py")
PROVIDER_MODEL_POLICY_FILES = ("src/repolens/provider.py",)
AGENT_PATH_POLICY_FILES = ("src/repolens/agent/tools.py",)


def policy_hashes(files=POLICY_FILES):
    return {name: hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for name in files}


def validate_policy():
    baseline = load_json(POLICY)
    current = policy_hashes()
    extension = load_json(LANGCHAIN_POLICY) if LANGCHAIN_POLICY.is_file() else None
    provider_extension = load_json(PROVIDER_MODEL_POLICY) if PROVIDER_MODEL_POLICY.is_file() else None
    agent_path_extension = load_json(AGENT_PATH_POLICY) if AGENT_PATH_POLICY.is_file() else None
    langchain_overrides = set(extension.get("overrides_original_policy_files", ())) if extension else set()
    if not langchain_overrides <= {"src/repolens/pipeline.py"}:
        raise RuntimeError("LangChain policy manifest attempts to override an unrelated V6 policy file.")
    provider_overrides = (
        set(provider_extension.get("overrides_original_policy_files", ())) if provider_extension else set()
    )
    if provider_extension and provider_overrides != {"src/repolens/provider.py"}:
        raise RuntimeError("Provider model policy manifest must only override provider.py.")
    agent_path_overrides = (
        set(agent_path_extension.get("overrides_original_policy_files", ())) if agent_path_extension else set()
    )
    if agent_path_extension and agent_path_overrides != set(AGENT_PATH_POLICY_FILES):
        raise RuntimeError("Agent path policy manifest must only override agent/tools.py.")
    overrides = langchain_overrides | provider_overrides | agent_path_overrides
    for name, expected in baseline["implementation_sha256_lf"].items():
        if name not in overrides and current.get(name) != expected:
            raise RuntimeError(
                "Parser/embedding/prompt/agent policy changed; run explicit review and record a new policy manifest."
            )
    extension_hash = None
    if extension:
        if extension.get("parent_policy_sha256") != sha256(POLICY):
            raise RuntimeError("LangChain policy manifest is not linked to the original V6 policy baseline.")
        if extension.get("implementation_sha256_lf") != policy_hashes(LANGCHAIN_POLICY_FILES):
            raise RuntimeError("LangChain adapter or retrieval policy changed; review and record a new manifest.")
        extension_hash = sha256(LANGCHAIN_POLICY)
    elif current != baseline["implementation_sha256_lf"]:
        if not provider_extension and not agent_path_extension:
            raise RuntimeError(
                "Parser/embedding/prompt/agent policy changed; run explicit review and record a new policy manifest."
            )
    provider_extension_hash = None
    if provider_extension:
        if provider_extension.get("parent_policy_sha256") != sha256(POLICY):
            raise RuntimeError("Provider model policy manifest is not linked to the original V6 policy baseline.")
        if provider_extension.get("implementation_sha256_lf") != policy_hashes(PROVIDER_MODEL_POLICY_FILES):
            raise RuntimeError("Provider implementation changed; review and record a new policy manifest.")
        provider_extension_hash = sha256(PROVIDER_MODEL_POLICY)
    agent_path_extension_hash = None
    if agent_path_extension:
        if agent_path_extension.get("parent_policy_sha256") != sha256(POLICY):
            raise RuntimeError("Agent path policy manifest is not linked to the original V6 policy baseline.")
        if agent_path_extension.get("implementation_sha256_lf") != policy_hashes(AGENT_PATH_POLICY_FILES):
            raise RuntimeError("Agent path binding changed; review and record a new manifest.")
        agent_path_extension_hash = sha256(AGENT_PATH_POLICY)
    return {"langchain_policy_sha256": extension_hash,
            "provider_model_policy_sha256": provider_extension_hash,
            "agent_path_policy_sha256": agent_path_extension_hash}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_contract() -> dict[str, Any]:
    policy_extensions = validate_policy()
    manifest = load_json(MANIFEST)
    if manifest.get("view_sha256") != sha256(VIEW):
        raise RuntimeError("V5 workbench view hash does not match its manifest.")
    for name, expected in manifest.get("source_files", {}).items():
        source = EVAL / name
        if not source.is_file() or sha256(source) != expected:
            raise RuntimeError(f"Frozen evaluation source hash mismatch: {name}")
    records = load_json(VIEW)
    for record in records:
        dataset = EVAL / record["run"]["dataset"]
        if sha256(dataset) != record["run"]["dataset_sha256"]:
            raise RuntimeError("Frozen dataset hash mismatch.")
    if len(records) != 6 or {item["group"] for item in records} != {"crossfile-v4", "validation-v4"}:
        raise RuntimeError("Expected six frozen evaluation views in two groups.")
    if any(item["citation_precision"] is not None or item["answer_accuracy"] is not None for item in records):
        raise RuntimeError("Unmeasured generation metrics must remain null.")
    case_count = sum(len(item["cases"]) for item in records)
    return {"view_sha256": sha256(VIEW), "source_hashes": manifest["source_files"],
            "view_count": len(records), "case_count": case_count, "policy_sha256": sha256(POLICY),
            **policy_extensions, "generation_metrics": "not_measured"}


class LangChainReplayStore:
    """Keep gold validation on IndexStore and route searches through the adapter."""

    def __init__(self, store):
        self.store = store

    def __getattr__(self, name):
        strategies = {"search": "keyword", "search_vector": "vector", "search_hybrid": "hybrid",
                      "search_graph": "graph"}
        if name not in strategies:
            return getattr(self.store, name)
        from repolens.langchain_integration import RepoLensRetriever

        def search(query, snapshot_id, *, limit=10, path_prefix=None):
            retriever = RepoLensRetriever(store=self.store, snapshot_id=snapshot_id,
                                          strategy=strategies[name], limit=limit, path_prefix=path_prefix)
            return [{**doc.metadata, "text": doc.page_content} for doc in retriever.invoke(query)]

        return search


def replay(index: Path, *, langchain_retriever: bool = False) -> dict[str, Any]:
    from repolens.evaluation import evaluate_dataset
    from repolens.index import IndexStore

    records = load_json(VIEW)
    replayed = []
    with IndexStore(index) as store:
        search_store = LangChainReplayStore(store) if langchain_retriever else store
        for record in records:
            run = record["run"]
            result = evaluate_dataset(EVAL / run["dataset"], search_store, run["snapshot_id"],
                                      limit=run["top_k"], strategy=run["strategy"])
            for key in ("recall@5", "recall@10", "mrr", "ndcg@10"):
                expected = record["metrics"][key]
                actual = result["metrics"][key]
                if abs(expected - actual) > 1e-12:
                    raise RuntimeError(f"Frozen metric changed: {record['id']} {key} {expected} != {actual}")
            if [case["id"] for case in record["cases"]] != [case["id"] for case in result["cases"]]:
                raise RuntimeError("Frozen case identities changed.")
            for expected, actual in zip(record["cases"], result["cases"]):
                for key in ("recall@5", "recall@10", "mrr", "ndcg@10", "retrieved_count"):
                    if abs(expected[key] - actual[key]) > 1e-12:
                        raise RuntimeError(f"Case regression: {record['id']} {expected['id']} {key}")
            replayed.append({"id": record["id"], "strategy": run["strategy"], "metrics": result["metrics"]})
    return {"index": str(index), "retriever": "langchain" if langchain_retriever else "native", "replayed": replayed}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run RepoLens V6 frozen evaluation regression gate.")
    parser.add_argument("--index", type=Path, help="Optional fixed index for retrieval replay.")
    parser.add_argument("--langchain-retriever", action="store_true", help="Replay through the optional LangChain adapter.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--freeze-policy", type=Path, help="Create a new reviewed policy manifest; never overwrites.")
    parser.add_argument("--freeze-langchain-policy", action="store_true",
                        help="Create the reviewed optional LangChain policy extension; never overwrites.")
    parser.add_argument("--freeze-provider-model-policy", action="store_true",
                        help="Create the reviewed provider model policy extension; never overwrites.")
    parser.add_argument("--freeze-agent-path-policy", action="store_true",
                        help="Create the reviewed Agent path-binding policy extension; never overwrites.")
    parser.add_argument("--reason", help="Explicit explanation for the new reviewed policy baseline.")
    args = parser.parse_args()
    if args.freeze_policy:
        if not args.reason or len(args.reason.strip()) < 20:
            parser.error("Recording a policy requires --reason (at least 20 characters).")
        with args.freeze_policy.open("x", encoding="utf-8", newline="\n") as output:
            json.dump({"reason": args.reason, "hash_normalization": "UTF-8 source bytes with CRLF normalized to LF",
                       "implementation_sha256_lf": policy_hashes()}, output, indent=2)
            output.write("\n")
        return 0
    if args.freeze_langchain_policy:
        if not args.reason or len(args.reason.strip()) < 20:
            parser.error("Recording a LangChain policy requires --reason (at least 20 characters).")
        with LANGCHAIN_POLICY.open("x", encoding="utf-8", newline="\n") as output:
            json.dump({
                "reason": args.reason,
                "parent_policy_sha256": sha256(POLICY),
                "overrides_original_policy_files": ["src/repolens/pipeline.py"],
                "hash_normalization": "UTF-8 source bytes with CRLF normalized to LF",
                "implementation_sha256_lf": policy_hashes(LANGCHAIN_POLICY_FILES),
            }, output, indent=2)
            output.write("\n")
        return 0
    if args.freeze_provider_model_policy:
        if not args.reason or len(args.reason.strip()) < 20:
            parser.error("Recording a provider model policy requires --reason (at least 20 characters).")
        with PROVIDER_MODEL_POLICY.open("x", encoding="utf-8", newline="\n") as output:
            json.dump({
                "reason": args.reason,
                "parent_policy_sha256": sha256(POLICY),
                "overrides_original_policy_files": ["src/repolens/provider.py"],
                "hash_normalization": "UTF-8 source bytes with CRLF normalized to LF",
                "implementation_sha256_lf": policy_hashes(PROVIDER_MODEL_POLICY_FILES),
            }, output, indent=2)
            output.write("\n")
        return 0
    if args.freeze_agent_path_policy:
        if not args.reason or len(args.reason.strip()) < 20:
            parser.error("Recording an Agent path policy requires --reason (at least 20 characters).")
        with AGENT_PATH_POLICY.open("x", encoding="utf-8", newline="\n") as output:
            json.dump({
                "reason": args.reason,
                "parent_policy_sha256": sha256(POLICY),
                "overrides_original_policy_files": list(AGENT_PATH_POLICY_FILES),
                "hash_normalization": "UTF-8 source bytes with CRLF normalized to LF",
                "implementation_sha256_lf": policy_hashes(AGENT_PATH_POLICY_FILES),
            }, output, indent=2)
            output.write("\n")
        return 0
    report = {"schema_version": "repolens.v6-regression.v1", "contract": validate_contract()}
    if args.langchain_retriever and not args.index:
        parser.error("--langchain-retriever requires --index.")
    if args.index:
        report["replay"] = replay(args.index, langchain_retriever=args.langchain_retriever)
    if args.output:
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
