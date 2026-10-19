"""Resolve a user-selected ref once, then query only its immutable snapshot."""

from repolens.domain import RepoLensError
from repolens.graph.query import GraphStore
from repolens.index import IndexStore
from repolens.ingestion import ingest_or_reuse


def inspect_graph(repository, directory, ref="HEAD", **selection):
    ingestion = ingest_or_reuse(repository, directory, ref)
    with IndexStore(directory) as store:
        result = GraphStore(store).subgraph(ingestion["snapshot_id"], **selection)
    if selection.get("commit") and result["stats"].get("deleted_paths"):
        base = ingest_or_reuse(repository, directory, result["stats"]["base_commit_sha"])
        with IndexStore(directory) as store:
            result["base_graph"] = GraphStore(store).for_paths(
                base["snapshot_id"], result["stats"]["deleted_paths"],
                hops=selection.get("hops", 1), max_nodes=selection.get("max_nodes", 100),
                max_edges=selection.get("max_edges", 200))
        result["base_graph"]["seed_reason"] = "Deleted paths are analyzed in the base snapshot, separately from head evidence."
    result["workflow"] = {"repository": ingestion["root"], "requested_ref": ref,
                          "commit_sha": ingestion["commit_sha"], "snapshot_id": ingestion["snapshot_id"],
                          "index_action": ingestion["index_action"]}
    return result


def search_version(repository, directory, query, ref="HEAD", *, strategy="graph", limit=10, path_prefix=None):
    methods = {"keyword": "search", "vector": "search_vector", "hybrid": "search_hybrid", "graph": "search_graph"}
    if strategy not in methods:
        raise RepoLensError("Search strategy must be keyword, vector, hybrid, or graph.")
    ingestion = ingest_or_reuse(repository, directory, ref)
    with IndexStore(directory) as store:
        results = getattr(store, methods[strategy])(query, ingestion["snapshot_id"], limit=limit, path_prefix=path_prefix)
    return {"schema_version": "repolens.version-search.v1", "query": query, "strategy": strategy,
            "snapshot_id": ingestion["snapshot_id"], "commit_sha": ingestion["commit_sha"], "results": results,
            "requested_ref": ref}
