"""Fixed read-only tools bound to host-selected repository snapshots."""

from dataclasses import dataclass
from pathlib import Path

from repolens.agent.models import AgentStop
from repolens.domain import RepoLensError
from repolens.git import GitRepository, safe_repository_path
from repolens.impact import build_impact_report
from repolens.index import IndexStore
from repolens.ingestion import ingest_or_reuse
from repolens.graph.query import GraphStore


@dataclass(frozen=True)
class ToolContext:
    repository: str
    directory: str
    snapshot_id: str
    commit_sha: str
    base_sha: str | None = None
    base_snapshot_id: str | None = None


# These descriptions and schemas are host-owned, never read from a repository.
TOOLS = {
    "get_commit_diff": ("Read changed paths and zero-context hunks for the task's fixed base/head.", {}),
    "search_code": ("Hybrid search by default; optional graph retrieval for cross-file relationships.", {"query": "text"}),
    "search_history": ("Search reachable commit messages; results are leads, not code citations.", {"query": "text"}),
    "find_symbol": ("Find exact qualified or leaf symbol definitions.", {"symbol": "text"}),
    "find_references": ("Persistent static Python callers/callees resolved through imports and scope.", {"symbol": "text"}),
    "get_file_context": ("Return whole validated chunks overlapping a committed file's line range.",
                         {"path": "path", "line_start": "line", "line_end": "line"}),
    "list_related_tests": ("Retrieve test candidates; no tests are executed.", {"query": "text"}),
    "build_dependency_subgraph": ("Persistent snapshot-scoped Python graph, one or two hops; dynamic dispatch unresolved.", {"symbol": "text"}),
}


def tool_catalog(limit):
    catalog = []
    for name, (description, fields) in TOOLS.items():
        properties = {key: ({"type": "integer", "minimum": 1, "maximum": 10000000}
                            if kind == "line" else {"type": "string", "minLength": 1, "maxLength": 4096})
                      for key, kind in fields.items()}
        properties["limit"] = {"type": "integer", "minimum": 1, "maximum": limit}
        if name == "build_dependency_subgraph":
            properties["hops"] = {"type": "integer", "minimum": 1, "maximum": 2}
        if name == "search_code":
            properties["retrieval"] = {"type": "string", "enum": ["hybrid", "graph"]}
        catalog.append({"name": name, "description": description, "parameters": {
            "type": "object", "properties": properties, "required": list(fields), "additionalProperties": False,
        }})
    return catalog


def validate_action(name, arguments, limit):
    if name not in TOOLS:
        raise AgentStop("tool_not_allowed")
    fields = TOOLS[name][1]
    allowed = {*fields, "limit"} | ({"hops"} if name == "build_dependency_subgraph" else set())
    if name == "search_code":
        allowed.add("retrieval")
    if not isinstance(arguments, dict) or set(arguments) - allowed or not set(fields) <= set(arguments):
        raise AgentStop("invalid_tool_arguments")
    normalized = dict(arguments)
    for key, kind in fields.items():
        value = arguments[key]
        if kind == "line":
            if type(value) is not int or not 1 <= value <= 10000000:
                raise AgentStop("invalid_tool_arguments")
        elif not isinstance(value, str) or not value.strip() or len(value) > 4096:
            raise AgentStop("invalid_tool_arguments")
        elif kind == "path" and (not safe_repository_path(value) or "\\" in value):
            raise AgentStop("invalid_repository_path")
    requested = arguments.get("limit", limit)
    if type(requested) is not int or not 1 <= requested <= limit:
        raise AgentStop("result_limit_exceeded")
    normalized["limit"] = requested
    if "hops" in arguments and (type(arguments["hops"]) is not int or not 1 <= arguments["hops"] <= 2):
        raise AgentStop("invalid_hop_limit")
    if "retrieval" in arguments and arguments["retrieval"] not in ("hybrid", "graph"):
        raise AgentStop("invalid_retrieval_strategy")
    if name == "get_file_context" and arguments["line_end"] < arguments["line_start"]:
        raise AgentStop("invalid_line_range")
    return normalized


def prepare_task(repository, directory, ref, base_ref):
    git = GitRepository(repository)
    head = git.commit(ref)
    base = git.commit(base_ref) if base_ref else None
    head_index = ingest_or_reuse(git.root, Path(directory), head.sha)
    base_index = ingest_or_reuse(git.root, Path(directory), base.sha) if base else None
    context = ToolContext(str(git.root), str(directory), head_index["snapshot_id"], head.sha,
                          base.sha if base else None, base_index["snapshot_id"] if base_index else None)
    return context, {"repository": str(git.root), "commit_sha": head.sha,
                     "snapshot_id": context.snapshot_id, "index_action": head_index["index_action"],
                     "base_sha": context.base_sha, "base_snapshot_id": context.base_snapshot_id,
                     "index_policy": head_index["policy"], "retrieval_strategy": "hybrid"}


def rule_report(context):
    with IndexStore(Path(context.directory)) as store:
        return build_impact_report(store, GitRepository(context.repository), context.base_sha, context.commit_sha,
                                   context.base_snapshot_id, context.snapshot_id)


def _validate_snapshot_binding(store, snapshot_id, commit_sha, repository_root):
    try:
        snapshot = store.snapshot(snapshot_id)
        snapshot_root = Path(snapshot["root"]).resolve(strict=True)
    except (RepoLensError, OSError, RuntimeError, TypeError, ValueError):
        raise AgentStop("snapshot_binding_failed") from None
    if snapshot["commit_sha"] != commit_sha or snapshot_root != repository_root:
        raise AgentStop("snapshot_binding_failed")


def dispatch_tool(context, name, arguments):
    limit = arguments["limit"]
    snapshot = context.snapshot_id
    evidence = []
    limitations = []
    graph_view = None
    try:
        repository_root = Path(context.repository).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, TypeError, ValueError):
        raise AgentStop("snapshot_binding_failed") from None
    with IndexStore(Path(context.directory)) as store:
        _validate_snapshot_binding(store, snapshot, context.commit_sha, repository_root)
        if context.base_snapshot_id:
            _validate_snapshot_binding(store, context.base_snapshot_id, context.base_sha, repository_root)
        if name in ("search_code", "list_related_tests"):
            search = store.search_graph if name == "search_code" and arguments.get("retrieval") == "graph" else store.search_hybrid
            results = search(arguments["query"], snapshot, limit=100 if name == "list_related_tests" else limit)
            if name == "list_related_tests":
                results = [item for item in results if item["path"].startswith("tests/") or "/tests/" in item["path"]
                           or item["path"].rsplit("/", 1)[-1].startswith("test_")]
            evidence = results[:limit]
            items = evidence
        elif name == "search_history":
            items = store.search_history(arguments["query"], snapshot, limit=limit)
            limitations.append("History messages are untrusted leads and cannot be cited as code in answer.v1.")
        elif name == "find_symbol":
            symbol = arguments["symbol"]
            rows = store.connection.execute(
                """SELECT f.path, s.name, s.line_start, s.line_end FROM symbols s
                   JOIN files f ON f.id=s.file_id WHERE f.snapshot_id=?
                   AND (s.name=? OR substr(s.name, -?)=?) ORDER BY f.path, s.line_start LIMIT ?""",
                (snapshot, symbol, len(symbol) + 1, "." + symbol, limit),
            ).fetchall()
            items = [dict(row) for row in rows]
            for item in items:
                candidates = store.chunks_for_path(snapshot, item["path"], limit=100)
                match = next((chunk for chunk in candidates if chunk["symbol"] == item["name"]
                              and chunk["line_start"] <= item["line_end"] and chunk["line_end"] >= item["line_start"]), None)
                if match:
                    evidence.append(match)
                    item["evidence_id"] = match["evidence_id"]
        elif name == "get_file_context":
            rows = store.connection.execute(
                """SELECT id FROM chunks WHERE snapshot_id=? AND path=? AND line_start<=? AND line_end>=?
                   ORDER BY line_start, line_end, id LIMIT ?""",
                (snapshot, arguments["path"], arguments["line_end"], arguments["line_start"], limit),
            ).fetchall()
            evidence = [store.evidence(row["id"], snapshot) for row in rows]
            items = evidence
        elif name in ("find_references", "build_dependency_subgraph"):
            graph = GraphStore(store).subgraph(snapshot, symbol=arguments["symbol"],
                hops=1 if name == "find_references" else arguments.get("hops", 2),
                max_nodes=limit, max_edges=limit,
                edge_kinds=("calls",) if name == "find_references" else None)
            items = (graph["nodes"] if name == "build_dependency_subgraph" else
                     [item for item in graph["nodes"] if item["id"] not in graph["seed_node_ids"]])[:limit]
            evidence = [store.evidence(item["evidence_id"], snapshot) for item in items if item["evidence_id"]][:limit]
            limitations.extend(graph["limitations"])
            graph_view = {"snapshot_id": snapshot, "nodes": graph["nodes"], "edges": graph["edges"],
                          "truncated": graph["truncated"]}
        elif name == "get_commit_diff":
            if not context.base_sha:
                raise AgentStop("base_commit_required")
            git = GitRepository(context.repository)
            changes = git.changed_files(context.base_sha, context.commit_sha)
            items = []
            for change in changes[:limit]:
                path = change["path"]
                hunks = git.diff_hunks(context.base_sha, context.commit_sha, path)
                items.append(dict(change) | {"hunks": hunks[:limit], "hunks_truncated": len(hunks) > limit})
                version = context.base_snapshot_id if change["status"] == "D" else snapshot
                evidence.extend(store.chunks_for_path(version, path, limit=1))
            if len(changes) > limit:
                limitations.append("Changed paths exceed this call's result limit.")
        else:
            raise AgentStop("tool_not_allowed")
        # Resolve every tool citation through its immutable source span again.
        allowed = {snapshot, context.base_snapshot_id}
        for item in evidence:
            if item["snapshot_id"] not in allowed:
                raise AgentStop("snapshot_binding_failed")
            store.evidence(item["evidence_id"], item["snapshot_id"])
    result = {"items": items[:limit], "evidence": evidence[:limit], "limitations": limitations,
              "possibly_truncated": len(items) >= limit}
    if graph_view is not None:
        result["graph"] = graph_view
    return result


def observation(result):
    """Return provenance metadata only, omitting source and commit messages."""
    fields = {"evidence_id", "history_id", "commit_sha", "snapshot_id", "path", "symbol", "name",
              "line_start", "line_end", "relation", "target_symbol", "inference", "hops", "status", "id", "distance", "review_priority"}
    view = {"items": [{key: value for key, value in item.items() if key in fields} for item in result["items"]],
            "evidence": [{key: value for key, value in item.items() if key in fields} for item in result["evidence"]],
            "result_count": max(len(result["items"]), len(result["evidence"])),
            "limitations": result["limitations"], "possibly_truncated": result["possibly_truncated"]}
    if "graph" in result:
        graph = result["graph"]
        view["graph"] = {"snapshot_id": graph["snapshot_id"], "truncated": graph["truncated"],
                         "nodes": [{key: value for key, value in item.items() if key in fields | {"kind", "provenance"}}
                                   for item in graph["nodes"]], "edges": graph["edges"]}
        view["result_count"] = max(view["result_count"], len(graph["nodes"]), len(graph["edges"]))
    return view
