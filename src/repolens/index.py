"""Transactional SQLite persistence and strictly snapshot-scoped FTS5 retrieval."""

from contextlib import AbstractContextManager
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3

from repolens.domain import (
    Chunk,
    Commit,
    INDEX_POLICY,
    ParsedFile,
    RepoLensError,
    Symbol,
    TreeEntry,
    source_lines,
    stable_id,
)
from repolens.embeddings import LocalTfidfEmbeddingProvider, cosine_similarity, load_provider
from repolens.git import safe_repository_path
from repolens.retrieval import query_expansion_terms, rerank_candidates
from repolens.graph.schema import GRAPH_SCHEMA


SCHEMA_VERSION = 4
DATABASE_NAME = "index.sqlite3"
FTS_BM25_WEIGHTS = (2.0, 6.0, 1.0)
FTS_QUERY_POLICY = "literal-unicode-terms-or-identifier-phrases-multilingual-v3"
VECTOR_POLICY = LocalTfidfEmbeddingProvider.provider_id
KEYWORD_RETRIEVAL_POLICY = "fts5-bm25-multilingual-coverage-rerank-v1"
VECTOR_RETRIEVAL_POLICY = "local-tfidf-cosine-v1"
RETRIEVAL_POLICY = "hybrid-rrf-keyword-vector-multilingual-v1"
FTS_CANDIDATE_LIMIT = 100
VECTOR_CANDIDATE_LIMIT = 100
SCHEMA = """
CREATE TABLE repositories (
    id TEXT PRIMARY KEY, root TEXT NOT NULL UNIQUE
);
CREATE TABLE snapshots (
    id TEXT PRIMARY KEY,
    repository_id TEXT NOT NULL REFERENCES repositories(id),
    commit_sha TEXT NOT NULL,
    commit_json TEXT NOT NULL,
    policy TEXT NOT NULL,
    created_at TEXT NOT NULL,
    stats_json TEXT NOT NULL,
    UNIQUE(repository_id, commit_sha, policy)
);
CREATE TABLE history_commits (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    commit_sha TEXT NOT NULL,
    parents_json TEXT NOT NULL,
    author TEXT NOT NULL,
    authored_at TEXT NOT NULL,
    message TEXT NOT NULL,
    UNIQUE(snapshot_id, commit_sha)
);
CREATE INDEX history_commits_snapshot ON history_commits(snapshot_id, authored_at DESC, commit_sha);
CREATE TABLE files (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    blob_id TEXT NOT NULL,
    mode TEXT NOT NULL,
    size INTEGER NOT NULL,
    status TEXT NOT NULL,
    language TEXT,
    content_hash TEXT,
    text TEXT,
    UNIQUE(snapshot_id, path)
);
CREATE TABLE symbols (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    line_start INTEGER NOT NULL CHECK(line_start >= 1),
    line_end INTEGER NOT NULL CHECK(line_end >= line_start)
);
CREATE TABLE chunks (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    symbol TEXT,
    kind TEXT NOT NULL,
    line_start INTEGER NOT NULL CHECK(line_start >= 1),
    line_end INTEGER NOT NULL CHECK(line_end >= line_start),
    text TEXT NOT NULL
);
CREATE INDEX chunks_snapshot_path ON chunks(snapshot_id, path);
CREATE TABLE vector_models (
    snapshot_id TEXT PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL,
    model_json TEXT NOT NULL
);
CREATE TABLE chunk_vectors (
    chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
    snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    vector_json TEXT NOT NULL
);
CREATE INDEX chunk_vectors_snapshot ON chunk_vectors(snapshot_id);
CREATE VIRTUAL TABLE history_fts USING fts5(
    commit_sha, author, message, content='history_commits', content_rowid='rowid', tokenize='unicode61'
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    path, symbol, text, content='chunks', content_rowid='rowid', tokenize='unicode61'
);
CREATE TRIGGER chunks_insert AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, path, symbol, text)
    VALUES (new.rowid, new.path, new.symbol, new.text);
END;
CREATE TRIGGER chunks_delete AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, path, symbol, text)
    VALUES ('delete', old.rowid, old.path, old.symbol, old.text);
END;
CREATE TRIGGER history_insert AFTER INSERT ON history_commits BEGIN
    INSERT INTO history_fts(rowid, commit_sha, author, message)
    VALUES (new.rowid, new.commit_sha, new.author, new.message);
END;
CREATE TRIGGER history_delete AFTER DELETE ON history_commits BEGIN
    INSERT INTO history_fts(history_fts, rowid, commit_sha, author, message)
    VALUES ('delete', old.rowid, old.commit_sha, old.author, old.message);
END;
PRAGMA user_version = 4;
""" + GRAPH_SCHEMA


def match_expression(query: str) -> str:
    if len(query) > 4096:
        raise RepoLensError("Search query is too long; use at most 4096 characters.")
    terms = list(dict.fromkeys(re.findall(r"[^\W_]+", query, re.UNICODE)))
    if not terms:
        raise RepoLensError("Search query must contain a letter or number.")
    identifiers = list(dict.fromkeys(
        term for term in re.findall(r"(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_.]*", query)
        if "_" in term or "." in term
    ))
    terms.extend(term for term in identifiers if term not in terms)
    terms.extend(term for term in query_expansion_terms(query) if term not in terms)
    if len(terms) > 64:
        raise RepoLensError("Search query has too many terms; use at most 64 unique terms.")
    # Treat user input as literal terms, never as an FTS operator expression.
    return " OR ".join('"' + term + '"' for term in terms)


class IndexStore(AbstractContextManager):
    def __init__(self, directory: Path, *, writable: bool = False):
        database = directory / DATABASE_NAME
        if writable:
            directory.mkdir(parents=True, exist_ok=True)
            self.connection = sqlite3.connect(database, timeout=5)
        else:
            if not database.is_file():
                raise RepoLensError("Index not found; run ingest first with the same --data-dir.")
            self.connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        try:
            version = self.connection.execute("PRAGMA user_version").fetchone()[0]
            if version == 0 and writable:
                if self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                    raise RepoLensError("Unrecognized database; select a separate --data-dir.")
                self.connection.executescript(SCHEMA)
            elif version == 1 and writable:
                self._migrate_v1()
            if writable and self.connection.execute("PRAGMA user_version").fetchone()[0] == 2:
                self._migrate_v2()
            if writable and self.connection.execute("PRAGMA user_version").fetchone()[0] == 3:
                self.connection.executescript("BEGIN;" + GRAPH_SCHEMA + "PRAGMA user_version=4; COMMIT;")
            if self.connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
                raise RepoLensError("Index schema is incompatible; rebuild into a new --data-dir.")
        except BaseException:
            self.connection.close()
            raise

    def __exit__(self, *exc_info):
        self.connection.close()
        return False

    def _migrate_v1(self) -> None:
        """Add vector tables and backfill old snapshots in one writable open."""

        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS vector_models (
                    snapshot_id TEXT PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
                    provider_id TEXT NOT NULL,
                    model_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunk_vectors (
                    chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
                    snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
                    vector_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS chunk_vectors_snapshot ON chunk_vectors(snapshot_id);
                PRAGMA user_version = 2;
                """
            )
        for row in self.connection.execute("SELECT id FROM snapshots ORDER BY id").fetchall():
            self._build_vector_index(row["id"])

    def _migrate_v2(self) -> None:
        """Add snapshot-scoped Git history tables to a vector index."""

        with self.connection:
            self.connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS history_commits (
                    id TEXT PRIMARY KEY,
                    snapshot_id TEXT NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
                    commit_sha TEXT NOT NULL,
                    parents_json TEXT NOT NULL,
                    author TEXT NOT NULL,
                    authored_at TEXT NOT NULL,
                    message TEXT NOT NULL,
                    UNIQUE(snapshot_id, commit_sha)
                );
                CREATE INDEX IF NOT EXISTS history_commits_snapshot
                    ON history_commits(snapshot_id, authored_at DESC, commit_sha);
                CREATE VIRTUAL TABLE IF NOT EXISTS history_fts USING fts5(
                    commit_sha, author, message, content='history_commits',
                    content_rowid='rowid', tokenize='unicode61'
                );
                CREATE TRIGGER IF NOT EXISTS history_insert AFTER INSERT ON history_commits BEGIN
                    INSERT INTO history_fts(rowid, commit_sha, author, message)
                    VALUES (new.rowid, new.commit_sha, new.author, new.message);
                END;
                CREATE TRIGGER IF NOT EXISTS history_delete AFTER DELETE ON history_commits BEGIN
                    INSERT INTO history_fts(history_fts, rowid, commit_sha, author, message)
                    VALUES ('delete', old.rowid, old.commit_sha, old.author, old.message);
                END;
                PRAGMA user_version = 3;
                """
            )

    def _build_vector_index(self, snapshot_id: str) -> None:
        rows = self.connection.execute(
            "SELECT id, text FROM chunks WHERE snapshot_id=? ORDER BY id", (snapshot_id,)
        ).fetchall()
        provider = LocalTfidfEmbeddingProvider()
        provider.fit(row["text"] for row in rows)
        with self.connection:
            self.connection.execute("DELETE FROM chunk_vectors WHERE snapshot_id=?", (snapshot_id,))
            self.connection.execute("DELETE FROM vector_models WHERE snapshot_id=?", (snapshot_id,))
            if not rows or not provider.fitted:
                return
            model = provider.model_json()
            self.connection.execute(
                "INSERT INTO vector_models VALUES (?, ?, ?)",
                (snapshot_id, provider.provider_id, json.dumps(model, ensure_ascii=True, separators=(",", ":"))),
            )
            for row in rows:
                vector = provider.embed(row["text"])
                self.connection.execute(
                    "INSERT INTO chunk_vectors VALUES (?, ?, ?)",
                    (row["id"], snapshot_id, json.dumps(vector, ensure_ascii=True, separators=(",", ":"))),
                )

    def save(self, root: Path, repository_id: str, snapshot_id: str, commit: Commit,
             files: list[ParsedFile], stats: dict, history: list[Commit] | None = None) -> None:
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO repositories VALUES (?, ?)", (repository_id, str(root)))
            # Replacement and FTS trigger updates share one transaction. A failed
            # rebuild must leave the previous complete snapshot usable.
            self.connection.execute("DELETE FROM snapshots WHERE id = ?", (snapshot_id,))
            self.connection.execute(
                "INSERT INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                (snapshot_id, repository_id, commit.sha, json.dumps(asdict(commit)), INDEX_POLICY,
                 datetime.now(timezone.utc).isoformat(), json.dumps(stats)),
            )
            for historical_commit in history or [commit]:
                history_id = stable_id("history", snapshot_id, historical_commit.sha)
                self.connection.execute(
                    "INSERT INTO history_commits VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (history_id, snapshot_id, historical_commit.sha,
                     json.dumps(historical_commit.parents, ensure_ascii=True),
                     historical_commit.author, historical_commit.authored_at, historical_commit.message),
                )
            for file in files:
                entry = file.entry
                file_id = stable_id("file", snapshot_id, entry.path, entry.object_id)
                self.connection.execute(
                    "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (file_id, snapshot_id, entry.path, entry.object_id, entry.mode, entry.size,
                     file.status, file.language, file.content_hash, file.text),
                )
                for symbol in file.symbols:
                    symbol_id = stable_id("symbol", file_id, symbol.name, symbol.kind, symbol.line_start, symbol.line_end)
                    self.connection.execute(
                        "INSERT INTO symbols VALUES (?, ?, ?, ?, ?, ?)",
                        (symbol_id, file_id, symbol.name, symbol.kind, symbol.line_start, symbol.line_end),
                    )
                for chunk in file.chunks:
                    evidence_id = stable_id(
                        "evidence", snapshot_id, entry.path, entry.object_id, chunk.kind,
                        chunk.symbol or "", chunk.line_start, chunk.line_end,
                    )
                    self.connection.execute(
                        "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (evidence_id, snapshot_id, file_id, entry.path, chunk.symbol,
                         chunk.kind, chunk.line_start, chunk.line_end, chunk.text),
                    )
            rows = self.connection.execute(
                "SELECT id, text FROM chunks WHERE snapshot_id=? ORDER BY id", (snapshot_id,)
            ).fetchall()
            provider = LocalTfidfEmbeddingProvider()
            provider.fit(row["text"] for row in rows)
            if rows and provider.fitted:
                model = provider.model_json()
                self.connection.execute(
                    "INSERT INTO vector_models VALUES (?, ?, ?)",
                    (snapshot_id, provider.provider_id,
                     json.dumps(model, ensure_ascii=True, separators=(",", ":"))),
                )
                for row in rows:
                    self.connection.execute(
                        "INSERT INTO chunk_vectors VALUES (?, ?, ?)",
                        (row["id"], snapshot_id,
                         json.dumps(provider.embed(row["text"]), ensure_ascii=True, separators=(",", ":"))),
                    )

            from repolens.graph.builder import build_graph

            build_graph(self, snapshot_id)

    def ensure_graph(self, snapshot_id: str) -> None:
        from repolens.graph.builder import build_graph
        from repolens.graph.schema import GRAPH_POLICY

        current = self.connection.execute("SELECT policy FROM graph_builds WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if current is None or current["policy"] != GRAPH_POLICY:
            with self.connection:
                build_graph(self, snapshot_id)

    def search_graph(self, query, snapshot_id, *, limit=5, path_prefix=None):
        from repolens.graph.query import GraphStore

        return GraphStore(self).search(query, snapshot_id, limit=limit, path_prefix=path_prefix)

    def snapshot_for_commit(self, repository_id: str, commit_sha: str) -> str | None:
        row = self.connection.execute(
            "SELECT id FROM snapshots WHERE repository_id=? AND commit_sha=? AND policy=? LIMIT 1",
            (repository_id, commit_sha, INDEX_POLICY),
        ).fetchone()
        return row["id"] if row else None

    def parsed_files(self, snapshot_id: str) -> dict[tuple[str, str], ParsedFile]:
        """Rehydrate parsed files for incremental indexing by path and blob."""

        self.snapshot(snapshot_id)
        file_rows = self.connection.execute(
            """SELECT id, path, blob_id, mode, size, status, language, content_hash, text
               FROM files WHERE snapshot_id=? ORDER BY path""",
            (snapshot_id,),
        ).fetchall()
        files: dict[tuple[str, str], ParsedFile] = {}
        for row in file_rows:
            symbols = tuple(
                Symbol(item["name"], item["kind"], item["line_start"], item["line_end"])
                for item in self.connection.execute(
                    "SELECT name, kind, line_start, line_end FROM symbols WHERE file_id=? "
                    "ORDER BY line_start, line_end, name", (row["id"],)
                ).fetchall()
            )
            chunks = tuple(
                Chunk(item["kind"], item["symbol"], item["line_start"], item["line_end"], item["text"])
                for item in self.connection.execute(
                    "SELECT kind, symbol, line_start, line_end, text FROM chunks WHERE file_id=? "
                    "ORDER BY line_start, line_end, id", (row["id"],)
                ).fetchall()
            )
            entry = TreeEntry(row["path"], row["blob_id"], row["mode"], row["size"])
            parsed = ParsedFile(
                entry=entry,
                status=row["status"],
                language=row["language"],
                content_hash=row["content_hash"],
                text=row["text"],
                symbols=symbols,
                chunks=chunks,
            )
            files[(entry.path, entry.object_id)] = parsed
        return files

    def snapshot(self, snapshot_id: str) -> dict:
        row = self.connection.execute(
            "SELECT s.*, r.root FROM snapshots s JOIN repositories r ON r.id=s.repository_id WHERE s.id=?",
            (snapshot_id,),
        ).fetchone()
        if row is None:
            raise RepoLensError("Snapshot not found; use snapshots to choose an indexed version.")
        return {
            "snapshot_id": row["id"], "repository_id": row["repository_id"],
            "root": row["root"], "commit_sha": row["commit_sha"], "policy": row["policy"],
            "created_at": row["created_at"], "stats": json.loads(row["stats_json"]),
        }

    def has_snapshot(self, snapshot_id: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM snapshots WHERE id=? LIMIT 1", (snapshot_id,)
        ).fetchone()
        return row is not None

    def snapshots(self) -> list[dict]:
        rows = self.connection.execute("SELECT id FROM snapshots ORDER BY created_at DESC, id LIMIT 100").fetchall()
        return [self.snapshot(row["id"]) for row in rows]

    def history(self, snapshot_id: str, *, limit: int = 100) -> list[dict]:
        """Return committed history reachable from one indexed snapshot."""

        if not 1 <= limit <= 5000:
            raise RepoLensError("History result limit must be between 1 and 5000.")
        self.snapshot(snapshot_id)
        rows = self.connection.execute(
            """SELECT id, snapshot_id, commit_sha, parents_json, author, authored_at, message
               FROM history_commits WHERE snapshot_id=?
               ORDER BY authored_at DESC, rowid ASC, commit_sha LIMIT ?""",
            (snapshot_id, limit),
        ).fetchall()
        return [
            {
                "history_id": row["id"],
                "snapshot_id": row["snapshot_id"],
                "commit_sha": row["commit_sha"],
                "parents": json.loads(row["parents_json"]),
                "author": row["author"],
                "authored_at": row["authored_at"],
                "message": row["message"],
            }
            for row in rows
        ]

    def search_history(self, query: str, snapshot_id: str, *, limit: int = 5) -> list[dict]:
        """Search only the selected snapshot's reachable commit history."""

        if not 1 <= limit <= 100:
            raise RepoLensError("History search limit must be between 1 and 100.")
        self.snapshot(snapshot_id)
        expression = match_expression(query)
        rows = self.connection.execute(
            """SELECT h.id, h.snapshot_id, h.commit_sha, h.parents_json,
                      h.author, h.authored_at, h.message,
                      bm25(history_fts, ?, ?, ?) AS score
               FROM history_fts JOIN history_commits h ON h.rowid=history_fts.rowid
               WHERE history_fts MATCH ? AND h.snapshot_id=?
               ORDER BY score, h.authored_at DESC, h.commit_sha LIMIT ?""",
            (2.0, 1.0, 1.0, expression, snapshot_id, limit),
        ).fetchall()
        return [
            {
                "history_id": row["id"],
                "snapshot_id": row["snapshot_id"],
                "commit_sha": row["commit_sha"],
                "parents": json.loads(row["parents_json"]),
                "author": row["author"],
                "authored_at": row["authored_at"],
                "message": row["message"],
                "history_score": row["score"],
            }
            for row in rows
        ]

    def files(self, snapshot_id: str, *, path: str | None = None) -> list[dict]:
        """Return indexed file metadata, optionally limited to one path."""

        self.snapshot(snapshot_id)
        rows = self.connection.execute(
            """SELECT id, path, blob_id, mode, size, status, language, content_hash
               FROM files WHERE snapshot_id=? AND (? IS NULL OR path=?) ORDER BY path""",
            (snapshot_id, path, path),
        ).fetchall()
        return [dict(row) for row in rows]

    def file_text(self, snapshot_id: str, path: str) -> str | None:
        """Return committed text for one indexed file without reading the worktree."""

        self.snapshot(snapshot_id)
        row = self.connection.execute(
            "SELECT text FROM files WHERE snapshot_id=? AND path=? LIMIT 1",
            (snapshot_id, path),
        ).fetchone()
        return row["text"] if row else None

    def symbols(self, snapshot_id: str, path: str) -> list[dict]:
        """Return all parsed symbols for one indexed repository-relative path."""

        self.snapshot(snapshot_id)
        rows = self.connection.execute(
            """SELECT s.name, s.kind, s.line_start, s.line_end
               FROM symbols s JOIN files f ON f.id=s.file_id
               WHERE f.snapshot_id=? AND f.path=?
               ORDER BY s.line_start, s.line_end, s.name""",
            (snapshot_id, path),
        ).fetchall()
        return [dict(row) for row in rows]

    def chunks_for_path(self, snapshot_id: str, path: str, *, limit: int = 20) -> list[dict]:
        """Return validated evidence chunks for one path."""

        if not 1 <= limit <= 100:
            raise RepoLensError("Evidence chunk limit must be between 1 and 100.")
        self.snapshot(snapshot_id)
        rows = self.connection.execute(
            """SELECT id FROM chunks
               WHERE snapshot_id=? AND path=?
               ORDER BY line_start, line_end, id LIMIT ?""",
            (snapshot_id, path, limit),
        ).fetchall()
        return [self.evidence(row["id"], snapshot_id) for row in rows]

    def evidence(self, evidence_id: str, snapshot_id: str) -> dict:
        row = self.connection.execute(
            """SELECT c.*, f.blob_id, f.content_hash, f.text AS file_text,
                      s.repository_id, s.commit_sha
               FROM chunks c JOIN files f ON f.id=c.file_id
               JOIN snapshots s ON s.id=c.snapshot_id
               WHERE c.id=? AND c.snapshot_id=?""", (evidence_id, snapshot_id),
        ).fetchone()
        if row is None:
            raise RepoLensError("Evidence not found in the selected snapshot; check both IDs.")
        lines = source_lines(row["file_text"])
        if (not 1 <= row["line_start"] <= row["line_end"] <= len(lines)
                or "".join(lines[row["line_start"] - 1:row["line_end"]]) != row["text"]):
            raise RepoLensError("Stored evidence failed its source-span check; rebuild this snapshot.")
        return {key: row[key] for key in (
            "snapshot_id", "repository_id", "commit_sha", "path", "blob_id", "content_hash",
            "symbol", "kind", "line_start", "line_end", "text",
        )} | {"evidence_id": row["id"]}

    def search(self, query: str, snapshot_id: str, *, limit: int = 5, path_prefix: str | None = None) -> list[dict]:
        if not 1 <= limit <= 100:
            raise RepoLensError("Search limit must be between 1 and 100.")
        self.snapshot(snapshot_id)
        expression = match_expression(query)
        if path_prefix is not None and not safe_repository_path(path_prefix.rstrip("/")):
            raise RepoLensError("Path prefix must be a safe repository-relative POSIX path.")
        rows = self.connection.execute(
            """SELECT c.id, c.path, c.symbol, c.line_start, c.line_end, c.text,
                      bm25(chunks_fts, ?, ?, ?) AS score
               FROM chunks_fts JOIN chunks c ON c.rowid=chunks_fts.rowid
               WHERE chunks_fts MATCH ? AND c.snapshot_id=?
                 AND trim(replace(replace(replace(c.text, char(10), ''), char(13), ''), char(9), '')) <> ''
                 AND (? IS NULL OR substr(c.path, 1, length(?)) = ?)
               ORDER BY score, c.path, c.line_start, c.id LIMIT ?""",
            (*FTS_BM25_WEIGHTS, expression, snapshot_id, path_prefix, path_prefix, path_prefix, FTS_CANDIDATE_LIMIT),
        ).fetchall()
        candidates = [dict(row) | {"bm25_score": row["score"]} for row in rows]
        candidates = rerank_candidates(candidates, query, limit)
        return [self.evidence(candidate["id"], snapshot_id) | {"bm25_score": candidate["bm25_score"]}
                for candidate in candidates]

    def search_vector(
        self, query: str, snapshot_id: str, *, limit: int = 5, path_prefix: str | None = None,
    ) -> list[dict]:
        """Search the persisted local embedding vectors for one snapshot."""

        if not 1 <= limit <= 100:
            raise RepoLensError("Search limit must be between 1 and 100.")
        self.snapshot(snapshot_id)
        match_expression(query)  # validate the same bounded query contract as lexical search
        model_row = self.connection.execute(
            "SELECT model_json FROM vector_models WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()
        if model_row is None:
            return []
        provider = load_provider(json.loads(model_row["model_json"]))
        query_vector = provider.embed(query)
        if not query_vector:
            return []
        if path_prefix is not None and not safe_repository_path(path_prefix.rstrip("/")):
            raise RepoLensError("Path prefix must be a safe repository-relative POSIX path.")
        rows = self.connection.execute(
            """SELECT c.id, c.path, c.symbol, c.line_start, c.line_end, c.text, v.vector_json
               FROM chunk_vectors v JOIN chunks c ON c.id=v.chunk_id
               WHERE v.snapshot_id=?
                 AND trim(replace(replace(replace(c.text, char(10), ''), char(13), ''), char(9), '')) <> ''
                 AND (? IS NULL OR substr(c.path, 1, length(?)) = ?)
               ORDER BY c.path, c.line_start, c.id""",
            (snapshot_id, path_prefix, path_prefix, path_prefix),
        ).fetchall()
        candidates = []
        for row in rows:
            vector = json.loads(row["vector_json"])
            score = cosine_similarity(query_vector, vector)
            if score <= 0.0:
                continue
            candidates.append(dict(row) | {"vector_score": score})
        candidates.sort(key=lambda item: (-item["vector_score"], item["path"], item["line_start"], item["id"]))
        candidates = candidates[:VECTOR_CANDIDATE_LIMIT]
        return [
            self.evidence(candidate["id"], snapshot_id) | {
                "vector_score": candidate["vector_score"],
                "retrieval_method": "vector",
            }
            for candidate in candidates[:limit]
        ]

    def search_hybrid(
        self, query: str, snapshot_id: str, *, limit: int = 5, path_prefix: str | None = None,
        keyword_weight: float = 0.55, vector_weight: float = 0.45,
    ) -> list[dict]:
        """Fuse lexical and vector ranks with deterministic weighted RRF."""

        if not 1 <= limit <= 100:
            raise RepoLensError("Search limit must be between 1 and 100.")
        if keyword_weight < 0 or vector_weight < 0 or keyword_weight + vector_weight <= 0:
            raise RepoLensError("Hybrid search weights must be non-negative and not both zero.")
        keyword = self.search(query, snapshot_id, limit=FTS_CANDIDATE_LIMIT, path_prefix=path_prefix)
        vector = self.search_vector(query, snapshot_id, limit=VECTOR_CANDIDATE_LIMIT, path_prefix=path_prefix)
        combined: dict[str, dict] = {}
        rrf_k = 60.0
        for rank, item in enumerate(keyword, 1):
            entry = combined.setdefault(item["evidence_id"], {"item": item, "keyword_rank": None, "vector_rank": None,
                                                                "hybrid_score": 0.0})
            entry["keyword_rank"] = rank
            entry["hybrid_score"] += keyword_weight / (rrf_k + rank)
        for rank, item in enumerate(vector, 1):
            entry = combined.setdefault(item["evidence_id"], {"item": item, "keyword_rank": None, "vector_rank": None,
                                                                "hybrid_score": 0.0})
            entry["vector_rank"] = rank
            entry["hybrid_score"] += vector_weight / (rrf_k + rank)
            if "vector_score" not in entry["item"]:
                entry["item"] = entry["item"] | {"vector_score": item["vector_score"]}
        ranked = sorted(
            combined.values(),
            key=lambda entry: (
                -entry["hybrid_score"], entry["item"]["path"], entry["item"]["line_start"], entry["item"]["evidence_id"],
            ),
        )
        results = []
        for entry in ranked[:limit]:
            results.append(entry["item"] | {
                "hybrid_score": entry["hybrid_score"],
                "keyword_rank": entry["keyword_rank"],
                "vector_rank": entry["vector_rank"],
                "retrieval_method": "hybrid",
            })
        return results
