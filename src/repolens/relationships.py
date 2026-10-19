"""Bounded, static Python caller/callee evidence for impact reports."""

import ast
from collections.abc import Mapping

from repolens.domain import RepoLensError


def _call_name(node: ast.Call) -> str | None:
    function = node.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def _definition_name(symbols: list[Mapping[str, object]], line: int) -> str | None:
    matches = [
        symbol for symbol in symbols
        if int(symbol["line_start"]) <= line <= int(symbol["line_end"])
    ]
    if not matches:
        return None
    return min(matches, key=lambda symbol: (int(symbol["line_end"]) - int(symbol["line_start"]), str(symbol["name"])))['name']


def _matches_target(symbol_name: str, target: str) -> bool:
    leaf = target.rsplit(".", 1)[-1]
    return symbol_name == target or symbol_name == leaf or symbol_name.endswith("." + leaf)


def _evidence_for_line(store, snapshot_id: str, path: str, line: int, cache: dict[str, list[dict]]) -> dict | None:
    if path not in cache:
        try:
            cache[path] = store.chunks_for_path(snapshot_id, path, limit=100)
        except RepoLensError:
            cache[path] = []
    chunks = cache[path]
    candidates = [chunk for chunk in chunks if chunk["line_start"] <= line <= chunk["line_end"]]
    if not candidates:
        return None
    return min(candidates, key=lambda chunk: (chunk["line_end"] - chunk["line_start"], chunk["line_start"]))


def find_call_relations(store, snapshot_id: str, targets: list[str], *, limit: int = 40) -> dict[str, list[dict]]:
    """Return direct caller/callee relations resolved against indexed symbols.

    This parser only inspects Python AST and never imports or executes repository
    code. A relation is returned only when its target resolves to an indexed
    definition in the selected snapshot.
    """

    if not targets:
        return {"callers": [], "callees": []}
    target_names = tuple(dict.fromkeys(targets))
    definitions: list[dict] = []
    parsed_files: list[tuple[str, ast.AST, list[Mapping[str, object]]]] = []
    functions: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef, str, list[Mapping[str, object]]]] = []
    for file in store.files(snapshot_id):
        if file.get("language") != "python":
            continue
        path = file["path"]
        text = store.file_text(snapshot_id, path)
        if text is None:
            continue
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError:
            continue
        symbols = store.symbols(snapshot_id, path)
        parsed_files.append((path, tree, symbols))
        definitions.extend({"path": path, **symbol} for symbol in symbols)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = _definition_name(symbols, node.lineno)
                if name:
                    functions.append((path, node, str(name), symbols))

    callers: list[dict] = []
    callees: list[dict] = []
    evidence_cache: dict[str, list[dict]] = {}
    seen_callers: set[tuple[str, str, int, str]] = set()
    seen_callees: set[tuple[str, str, int, str]] = set()
    for path, tree, symbols in parsed_files:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or node.lineno is None:
                continue
            called = _call_name(node)
            if not called:
                continue
            caller = _definition_name(symbols, node.lineno)
            if not caller:
                continue
            evidence = _evidence_for_line(store, snapshot_id, path, node.lineno, evidence_cache)
            if evidence is None:
                continue
            for target in target_names:
                if not _matches_target(called, target):
                    continue
                definition = next(
                    (item for item in definitions if _matches_target(str(item["name"]), target)),
                    None,
                )
                if definition is None:
                    continue
                caller_key = (path, caller, node.lineno, target)
                if caller_key not in seen_callers:
                    seen_callers.add(caller_key)
                    callers.append({
                        "relation": "caller",
                        "target_symbol": target,
                        "path": path,
                        "symbol": caller,
                        "line_start": node.lineno,
                        "line_end": getattr(node, "end_lineno", node.lineno),
                        "evidence": evidence,
                    })

    for target in target_names:
        for path, node, definition_name, _symbols in functions:
            if not _matches_target(definition_name, target):
                continue
            for call in ast.walk(node):
                if not isinstance(call, ast.Call) or call.lineno is None:
                    continue
                called = _call_name(call)
                if not called or _matches_target(called, target):
                    continue
                callee = next(
                    (item for item in definitions if _matches_target(str(item["name"]), called)),
                    None,
                )
                if callee is None:
                    continue
                evidence = _evidence_for_line(store, snapshot_id, path, call.lineno, evidence_cache)
                if evidence is None:
                    continue
                callee_key = (path, definition_name, call.lineno, str(callee["name"]))
                if callee_key in seen_callees:
                    continue
                seen_callees.add(callee_key)
                callees.append({
                    "relation": "callee",
                    "target_symbol": str(callee["name"]),
                    "path": path,
                    "symbol": definition_name,
                    "line_start": call.lineno,
                    "line_end": getattr(call, "end_lineno", call.lineno),
                    "evidence": evidence,
                })
    return {"callers": callers[:limit], "callees": callees[:limit]}
