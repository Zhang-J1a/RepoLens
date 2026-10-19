"""Shared immutable records and versioned identity policy."""

from dataclasses import dataclass
import hashlib
import json


INDEX_POLICY = "git-objects-v3_ast-md-atx_lines80-overlap15_local-tfidf-v1_history-v1"
MAX_FILE_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_TREE_ENTRIES = 50_000
MAX_HISTORY_COMMITS = 5_000
MAX_HISTORY_MESSAGE_BYTES = 64 * 1024


class RepoLensError(Exception):
    """An expected operation failure that is safe to show without a traceback."""


def stable_id(kind: str, *parts: str | int) -> str:
    payload = json.dumps(parts, ensure_ascii=True, separators=(",", ":"))
    return f"{kind}_{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


@dataclass(frozen=True)
class Commit:
    sha: str
    parents: tuple[str, ...]
    author: str
    authored_at: str
    message: str


@dataclass(frozen=True)
class TreeEntry:
    path: str
    object_id: str
    mode: str
    size: int


@dataclass(frozen=True)
class Symbol:
    name: str
    kind: str
    line_start: int
    line_end: int


@dataclass(frozen=True)
class Chunk:
    kind: str
    symbol: str | None
    line_start: int
    line_end: int
    text: str


@dataclass(frozen=True)
class ParsedFile:
    entry: TreeEntry
    status: str
    language: str | None = None
    content_hash: str | None = None
    text: str | None = None
    symbols: tuple[Symbol, ...] = ()
    chunks: tuple[Chunk, ...] = ()


def source_lines(text: str) -> list[str]:
    """Split LF-normalized source without treating Unicode separators as lines."""
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
