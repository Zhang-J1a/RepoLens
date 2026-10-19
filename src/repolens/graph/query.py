"""Bounded subgraphs, canonical provenance checks and graph-augmented retrieval."""

from collections import deque
import json
import re

from repolens.domain import RepoLensError, source_lines
from repolens.git import safe_repository_path
from repolens.graph.schema import EDGE_KINDS, GRAPH_POLICY, GRAPH_RETRIEVAL_POLICY, NODE_KINDS, SEMANTIC_EDGES


def _integer(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise RepoLensError(f"Graph {label} must be an integer between {minimum} and {maximum}.")


class GraphStore:
    def __init__(self, store):
        self.store = store
        self.connection = store.connection

    def info(self, snapshot_id):
        snapshot = self.store.snapshot(snapshot_id)
        row = self.connection.execute("SELECT * FROM graph_builds WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if row is None or row["policy"] != GRAPH_POLICY:
            raise RepoLensError("Code graph is missing or outdated; run ingest for this repository and ref first.")
        return {"snapshot_id": snapshot_id, "commit_sha": snapshot["commit_sha"], "graph_policy": row["policy"],
                "stats": json.loads(row["stats_json"])}

    def _validate_provenance(self, value, snapshot_id, evidence_id, cache):
        snapshot = self.store.snapshot(snapshot_id)
        if value.get("snapshot_id") != snapshot_id or value.get("commit_sha") != snapshot["commit_sha"]:
            raise RepoLensError("Graph provenance failed its snapshot binding check; rebuild the graph.")
        path = value.get("path")
        if path:
            files = self.store.files(snapshot_id, path=path)
            if not files or files[0]["blob_id"] != value.get("blob_id"):
                raise RepoLensError("Graph provenance does not match an indexed file.")
            line = value.get("line_start")
            if line is not None:
                text = self.store.file_text(snapshot_id, path)
                if type(line) is not int or text is None or not 1 <= line <= len(source_lines(text)):
                    raise RepoLensError("Graph source line is outside the selected file.")
        if evidence_id:
            if evidence_id not in cache:
                cache[evidence_id] = self.store.evidence(evidence_id, snapshot_id)
            item = cache[evidence_id]
            line = value.get("line_start")
            if item["path"] != path or line is not None and not item["line_start"] <= line <= item["line_end"]:
                raise RepoLensError("Graph evidence does not contain the declared source location.")

    def _node(self, row, cache):
        value = dict(row)
        value["provenance"] = json.loads(value.pop("provenance_json"))
        value["properties"] = json.loads(value.pop("properties_json"))
        if value["kind"] not in NODE_KINDS:
            raise RepoLensError("Graph contains an unknown node type.")
        if value["path"] != value["provenance"].get("path") or value["line_start"] != value["provenance"].get("line_start"):
            raise RepoLensError("Graph node locator disagrees with its provenance.")
        self._validate_provenance(value["provenance"], value["snapshot_id"], value["evidence_id"], cache)
        if value["symbol"]:
            source = self.connection.execute(
                """SELECT 1 FROM symbols s JOIN files f ON f.id=s.file_id WHERE f.snapshot_id=? AND f.path=?
                   AND s.name=? AND s.line_start<=? AND s.line_end>=? LIMIT 1""",
                (value["snapshot_id"], value["path"], value["symbol"], value["line_start"], value["line_end"]),
            ).fetchone()
            if source is None:
                raise RepoLensError("Graph symbol does not match an indexed source definition.")
        return value

    def _edge(self, row, cache):
        value = dict(row)
        value["provenance"] = json.loads(value.pop("provenance_json"))
        value["inference"] = bool(value["inference"])
        if value["kind"] not in EDGE_KINDS:
            raise RepoLensError("Graph contains an unknown edge type.")
        self._validate_provenance(value["provenance"], value["snapshot_id"], value["evidence_id"], cache)
        return value

    def subgraph(self, snapshot_id, *, symbol=None, path=None, commit=False, node_ids=None,
                 hops=1, max_nodes=100, max_edges=200, edge_kinds=None):
        info = self.info(snapshot_id)
        _integer(hops, 1, 2, "hops")
        _integer(max_nodes, 1, 500, "max_nodes")
        _integer(max_edges, 1, 2000, "max_edges")
        if path is not None and (not isinstance(path, str) or not safe_repository_path(path)):
            raise RepoLensError("Graph path must be a safe repository-relative path.")
        if symbol is not None and (not isinstance(symbol, str) or not symbol.strip() or len(symbol) > 512):
            raise RepoLensError("Graph symbol must be non-empty text of at most 512 characters.")
        if type(commit) is not bool:
            raise RepoLensError("Graph commit selector must be a boolean.")
        if sum((bool(symbol), bool(path) and not bool(symbol), bool(commit), node_ids is not None)) != 1:
            raise RepoLensError("Choose one graph seed: symbol (optionally with path), path, commit, or node IDs.")
        kinds = tuple(sorted(EDGE_KINDS if edge_kinds is None else edge_kinds))
        if not kinds or any(kind not in EDGE_KINDS for kind in kinds):
            raise RepoLensError("Graph edge kinds must be known relation types.")
        if node_ids is not None:
            if not isinstance(node_ids, (list, tuple)) or not node_ids or len(node_ids) > 100 or any(not isinstance(item, str) for item in node_ids):
                raise RepoLensError("Graph seed IDs must contain 1..100 node IDs.")
            placeholders = ",".join("?" for _ in node_ids)
            seeds = self.connection.execute(
                f"SELECT * FROM graph_nodes WHERE snapshot_id=? AND id IN ({placeholders}) ORDER BY id LIMIT ?",
                (snapshot_id, *node_ids, max_nodes + 1),
            ).fetchall()
            if {row["id"] for row in seeds} != set(node_ids):
                raise RepoLensError("A graph seed does not belong to the selected snapshot.")
        elif symbol:
            seeds = self.connection.execute(
                """SELECT * FROM graph_nodes WHERE snapshot_id=? AND (symbol=? OR substr(symbol,-?)=?)
                   AND (? IS NULL OR path=?) ORDER BY path,line_start,id LIMIT ?""",
                (snapshot_id, symbol, len(symbol) + 1, "." + symbol, path, path, max_nodes + 1),
            ).fetchall()
        elif path:
            seeds = self.connection.execute(
                "SELECT * FROM graph_nodes WHERE snapshot_id=? AND path=? ORDER BY symbol IS NULL, line_start,id LIMIT ?",
                (snapshot_id, path, max_nodes + 1),
            ).fetchall()
        else:
            seeds = self.connection.execute(
                """SELECT DISTINCT n.* FROM graph_nodes n WHERE n.snapshot_id=? AND (
                   (n.kind='commit' AND n.name=?) OR n.path IN (
                       SELECT f.path FROM graph_edges e JOIN graph_nodes c ON c.id=e.source_id
                       JOIN graph_nodes f ON f.id=e.target_id
                       WHERE e.snapshot_id=? AND e.kind='modifies' AND c.name=?))
                   ORDER BY n.symbol IS NULL,n.path,n.line_start,n.id LIMIT ?""",
                (snapshot_id, info["commit_sha"], snapshot_id, info["commit_sha"], max_nodes + 1),
            ).fetchall()
        truncated = len(seeds) > max_nodes
        seeds = seeds[:max_nodes]
        cache = {}
        nodes = {row["id"]: self._node(row, cache) | {"distance": 0} for row in seeds}
        edges = {}
        frontier = deque((identity, 0) for identity in nodes)
        while frontier:
            identity, depth = frontier.popleft()
            if depth >= hops:
                continue
            placeholders = ",".join("?" for _ in kinds)
            rows = self.connection.execute(
                f"""SELECT * FROM graph_edges WHERE snapshot_id=? AND (source_id=? OR target_id=?)
                    AND kind IN ({placeholders}) ORDER BY kind,id LIMIT ?""",
                (snapshot_id, identity, identity, *kinds, max_edges + 1),
            ).fetchall()
            if len(rows) > max_edges:
                truncated = True
            for row in rows:
                if row["id"] in edges:
                    continue
                other = row["target_id"] if row["source_id"] == identity else row["source_id"]
                if len(edges) >= max_edges or other not in nodes and len(nodes) >= max_nodes:
                    truncated = True
                    continue
                if other not in nodes:
                    other_row = self.connection.execute("SELECT * FROM graph_nodes WHERE snapshot_id=? AND id=?", (snapshot_id, other)).fetchone()
                    if other_row is None:
                        raise RepoLensError("Graph edge points outside its snapshot.")
                    nodes[other] = self._node(other_row, cache) | {"distance": depth + 1}
                    frontier.append((other, depth + 1))
                edges[row["id"]] = self._edge(row, cache)
        for item in nodes.values():
            item["review_priority"] = round((3 if item["kind"] in ("function", "class", "interface") else 2 if item["kind"] == "test" else 1)
                                            / (1 + item["distance"]), 3)
        return {"schema_version": "repolens.graph.v1", **info, "hops": hops,
                "seed_node_ids": [row["id"] for row in seeds], "ambiguous_seed": bool(symbol) and len(seeds) > 1,
                "nodes": list(nodes.values()), "edges": list(edges.values()), "truncated": truncated,
                "evidence": [{key: value for key, value in item.items() if key != "text"} for item in cache.values()],
                "limitations": ["Static Python definitions, imports and uniquely resolved calls only; dynamic dispatch and external libraries are unresolved.",
                                "Document edges are explicit qualified-name mentions, marked as inference. Review priority is not a risk severity.",
                                "Commit seeds cover symbols in changed surviving files; deleted-file code requires the base snapshot."]}

    def search(self, query, snapshot_id, *, limit=5, path_prefix=None):
        self.info(snapshot_id)
        _integer(limit, 1, 100, "result limit")
        vector = self.store.search_vector(query, snapshot_id, limit=100, path_prefix=path_prefix)
        terms = list(dict.fromkeys(re.findall(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", query)))[:64]
        if terms:
            placeholders = ",".join("?" for _ in terms)
            seeds = self.connection.execute(
                f"SELECT id FROM graph_nodes WHERE snapshot_id=? AND symbol IN ({placeholders}) ORDER BY id LIMIT 8",
                (snapshot_id, *terms),
            ).fetchall()
        else:
            seeds = []
        if not seeds:
            seeds = []
            for item in vector[:5]:
                rows = self.connection.execute(
                    "SELECT id FROM graph_nodes WHERE snapshot_id=? AND path=? AND symbol=? ORDER BY id LIMIT 1",
                    (snapshot_id, item["path"], item["symbol"]),
                ).fetchall()
                seeds.extend(rows)
        candidates = {item["evidence_id"]: dict(item) | {"graph_score": 0.4 / (60 + rank), "graph_hops": None}
                      for rank, item in enumerate(vector, 1)}
        seed_ids = list(dict.fromkeys(row["id"] for row in seeds))
        if seed_ids:
            graph = self.subgraph(snapshot_id, node_ids=seed_ids, hops=2, max_nodes=120, max_edges=300, edge_kinds=SEMANTIC_EDGES)
            ordered = sorted(graph["nodes"], key=lambda item: (item["distance"], item["id"]))
            for rank, node in enumerate(ordered, 1):
                if node["path"] is None or path_prefix is not None and not node["path"].startswith(path_prefix):
                    continue
                rows = self.connection.execute(
                    """SELECT id FROM chunks WHERE snapshot_id=? AND path=? AND (symbol=? OR (symbol IS NULL AND ? IS NULL))
                       ORDER BY line_start,id LIMIT 2""",
                    (snapshot_id, node["path"], node["symbol"], node["symbol"]),
                ).fetchall()
                for row in rows:
                    item = self.store.evidence(row["id"], snapshot_id)
                    score = (0.6 if node["distance"] else 1.0) / ((60 + rank) * max(1, node["distance"]))
                    previous = candidates.get(item["evidence_id"], {})
                    candidates[item["evidence_id"]] = item | {"graph_score": previous.get("graph_score", 0) + score,
                        "graph_hops": min(previous.get("graph_hops") or 3, node["distance"]),
                        "graph_node_id": node["id"], "graph_policy": GRAPH_RETRIEVAL_POLICY}
        return sorted(candidates.values(), key=lambda item: (-item["graph_score"], item["evidence_id"]))[:limit]

    def for_paths(self, snapshot_id, paths, *, hops=2, max_nodes=100, max_edges=200):
        info = self.info(snapshot_id)
        paths = list(dict.fromkeys(paths))
        _integer(hops, 1, 2, "hops")
        _integer(max_nodes, 1, 500, "max_nodes")
        _integer(max_edges, 1, 2000, "max_edges")
        if any(not isinstance(path, str) or not safe_repository_path(path) for path in paths):
            raise RepoLensError("Graph paths must be safe repository-relative paths.")
        paths = paths[:500]
        placeholders = ",".join("?" for _ in paths)
        seeds = self.connection.execute(
            f"SELECT id FROM graph_nodes WHERE snapshot_id=? AND path IN ({placeholders}) ORDER BY symbol IS NULL,path,line_start,id LIMIT ?",
            (snapshot_id, *paths, min(100, max_nodes)),
        ).fetchall() if paths else []
        if seeds:
            result = self.subgraph(snapshot_id, node_ids=[item["id"] for item in seeds], hops=hops,
                                   max_nodes=max_nodes, max_edges=max_edges)
        else:
            result = {"schema_version": "repolens.graph.v1", **info, "hops": hops, "seed_node_ids": [],
                      "ambiguous_seed": False, "nodes": [], "edges": [], "evidence": [], "truncated": False, "limitations": []}
        result["seed_paths"] = paths
        result["seed_selection_may_be_truncated"] = len(seeds) >= min(100, max_nodes)
        return result
