"""Python AST and bounded Markdown ATX-section parsing without source execution."""

import ast
import hashlib
import io
from pathlib import PurePosixPath
import re
import tokenize

from repolens.domain import Chunk, ParsedFile, Symbol, TreeEntry, source_lines


CHUNK_LINES = 80
OVERLAP_LINES = 15


def language_for(path: str) -> str | None:
    suffix = PurePosixPath(path).suffix.lower()
    return {".py": "python", ".md": "markdown", ".markdown": "markdown"}.get(suffix)


def _chunks(lines: list[str], start: int, end: int, kind: str, symbol: str | None = None) -> list[Chunk]:
    chunks = []
    while start <= end:
        stop = min(start + CHUNK_LINES - 1, end)
        chunks.append(Chunk(kind, symbol, start, stop, "".join(lines[start - 1:stop])))
        if stop == end:
            break
        start = stop - OVERLAP_LINES + 1
    return chunks


class _Symbols(ast.NodeVisitor):
    def __init__(self):
        self.scope: list[tuple[str, str]] = []
        self.nodes: list[tuple[Symbol, ast.AST]] = []

    def _visit_definition(self, node, kind: str) -> None:
        if kind == "function" and self.scope and self.scope[-1][1] == "class":
            kind = "method"
        if isinstance(node, ast.AsyncFunctionDef):
            kind = "async_" + kind
        name = ".".join([part[0] for part in self.scope] + [node.name])
        start = min([node.lineno] + [decorator.lineno for decorator in node.decorator_list])
        self.nodes.append((Symbol(name, kind, start, node.end_lineno), node))
        self.scope.append((node.name, "class" if isinstance(node, ast.ClassDef) else "function"))
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node):
        self._visit_definition(node, "class")

    def visit_FunctionDef(self, node):
        self._visit_definition(node, "function")

    def visit_AsyncFunctionDef(self, node):
        self._visit_definition(node, "function")


def _python(text: str, lines: list[str]) -> tuple[list[Symbol], list[Chunk], str]:
    try:
        tree = ast.parse(text)
        visitor = _Symbols()
        visitor.visit(tree)
    except (SyntaxError, ValueError, RecursionError):
        return [], _chunks(lines, 1, len(lines), "python_fallback"), "parse_fallback"
    symbols, chunks, covered = [], [], set()
    for symbol, node in visitor.nodes:
        symbols.append(symbol)
        covered.update(range(symbol.line_start, symbol.line_end + 1))
        end = symbol.line_end
        if symbol.kind == "class":
            children = [
                child for child in node.body
                if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if children:
                child = children[0]
                end = min([child.lineno] + [item.lineno for item in child.decorator_list]) - 1
        chunks.extend(_chunks(lines, symbol.line_start, max(symbol.line_start, end), symbol.kind, symbol.name))
    start = 1
    while start <= len(lines):
        if start in covered:
            start += 1
            continue
        end = start
        while end < len(lines) and end + 1 not in covered:
            end += 1
        chunks.extend(_chunks(lines, start, end, "module"))
        start = end + 1
    return symbols, chunks, "indexed"


def _markdown(lines: list[str]) -> list[Chunk]:
    starts: list[tuple[int, str | None]] = [(1, None)]
    headings: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    for number, line in enumerate(lines, 1):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line.rstrip("\n"))
        if marker:
            run, rest = marker.groups()
            if fence is None:
                fence = (run[0], len(run))
            elif run[0] == fence[0] and len(run) >= fence[1] and not rest.strip():
                fence = None
            continue
        if fence:
            continue
        heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)\s*$", line)
        if heading:
            level, title = len(heading[1]), re.sub(r"\s+#+\s*$", "", heading[2])
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, title))
            label = " / ".join(item[1] for item in headings)
            if number == 1:
                starts[0] = (1, label)
            else:
                starts.append((number, label))
    chunks = []
    for index, (start, label) in enumerate(starts):
        end = starts[index + 1][0] - 1 if index + 1 < len(starts) else len(lines)
        chunks.extend(_chunks(lines, start, end, "markdown_section", label))
    return chunks


def parse_file(entry: TreeEntry, raw: bytes) -> ParsedFile:
    language = language_for(entry.path)
    if b"\x00" in raw:
        return ParsedFile(entry, "binary", language)
    try:
        encoding = tokenize.detect_encoding(io.BytesIO(raw).readline)[0] if language == "python" else "utf-8-sig"
        text = raw.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
    except (UnicodeError, LookupError, SyntaxError):
        return ParsedFile(entry, "decode_error", language)
    lines = source_lines(text)
    if language == "python":
        symbols, chunks, status = _python(text, lines)
    else:
        symbols, chunks, status = [], _markdown(lines), "indexed"
    return ParsedFile(
        entry, status, language, hashlib.sha256(raw).hexdigest(), text,
        tuple(symbols), tuple(chunks),
    )
