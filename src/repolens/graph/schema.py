"""Snapshot-scoped graph schema; graph policy is independent of chunk policy."""

GRAPH_POLICY = "python-import-scope-graph-v2"
GRAPH_RETRIEVAL_POLICY = "vector-static-graph-rrf-v2"
NODE_KINDS = frozenset({"repository", "branch", "commit", "file", "module", "function", "class",
                        "interface", "test", "configuration", "document"})
EDGE_KINDS = frozenset({"contains", "defines", "calls", "imports", "implements", "tests",
                        "documents", "modifies", "depends_on", "replaces"})
SEMANTIC_EDGES = ("calls", "implements", "tests", "documents", "depends_on")
GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_builds (
    snapshot_id TEXT PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
    policy TEXT NOT NULL, stats_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS graph_nodes (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    kind TEXT NOT NULL, name TEXT NOT NULL, path TEXT, symbol TEXT,
    line_start INTEGER, line_end INTEGER, evidence_id TEXT REFERENCES chunks(id),
    provenance_json TEXT NOT NULL, properties_json TEXT NOT NULL,
    UNIQUE(snapshot_id, id)
);
CREATE INDEX IF NOT EXISTS graph_nodes_lookup ON graph_nodes(snapshot_id, symbol, path, kind);
CREATE TABLE IF NOT EXISTS graph_edges (
    id TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL,
    evidence_id TEXT REFERENCES chunks(id), provenance_json TEXT NOT NULL,
    inference INTEGER NOT NULL CHECK(inference IN (0, 1)),
    FOREIGN KEY(snapshot_id, source_id) REFERENCES graph_nodes(snapshot_id, id) ON DELETE CASCADE,
    FOREIGN KEY(snapshot_id, target_id) REFERENCES graph_nodes(snapshot_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS graph_edges_source ON graph_edges(snapshot_id, source_id, kind);
CREATE INDEX IF NOT EXISTS graph_edges_target ON graph_edges(snapshot_id, target_id, kind);
CREATE TABLE IF NOT EXISTS graph_file_facts (
    snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path TEXT NOT NULL, blob_id TEXT NOT NULL, facts_json TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, path)
);
"""
