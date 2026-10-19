"""Incremental syntax facts and snapshot-local static relation linking."""

from collections import defaultdict
import json
import re

from repolens.domain import RepoLensError, stable_id
from repolens.git import GitRepository
from repolens.graph.parsing import extract_facts, module_name
from repolens.graph.schema import GRAPH_POLICY


def _is_test(path):
    return path.startswith("tests/") or "/tests/" in path or path.rsplit("/", 1)[-1].startswith("test_")


def build_graph(store, snapshot_id):
    """Caller owns the transaction, so a failed build cannot publish half a graph."""
    connection = store.connection
    snapshot = store.snapshot(snapshot_id)
    commit = json.loads(connection.execute("SELECT commit_json FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()[0])
    parent = connection.execute(
        """SELECT s.id FROM snapshots s JOIN graph_builds g ON g.snapshot_id=s.id
           WHERE s.repository_id=? AND s.commit_sha=? AND g.policy=? ORDER BY s.created_at DESC LIMIT 1""",
        (snapshot["repository_id"], commit["parents"][0] if commit["parents"] else "", GRAPH_POLICY),
    ).fetchone()
    cached = {}
    if parent:
        cached = {row["path"]: (row["blob_id"], json.loads(row["facts_json"])) for row in connection.execute(
            "SELECT * FROM graph_file_facts WHERE snapshot_id=?", (parent["id"],))}
    connection.execute("DELETE FROM graph_builds WHERE snapshot_id=?", (snapshot_id,))
    connection.execute("DELETE FROM graph_nodes WHERE snapshot_id=?", (snapshot_id,))
    connection.execute("DELETE FROM graph_file_facts WHERE snapshot_id=?", (snapshot_id,))
    files = {row["path"]: dict(row) for row in connection.execute(
        "SELECT * FROM files WHERE snapshot_id=? ORDER BY path", (snapshot_id,))}
    chunks = defaultdict(list)
    for row in connection.execute("SELECT id, path, symbol, line_start, line_end FROM chunks WHERE snapshot_id=? ORDER BY line_start, id", (snapshot_id,)):
        chunks[row["path"]].append(dict(row))
    facts = {}
    reused = 0
    for path, file in files.items():
        if path in cached and cached[path][0] == file["blob_id"]:
            facts[path] = cached[path][1]
            reused += 1
        else:
            facts[path] = extract_facts(path, file["text"])
        connection.execute("INSERT INTO graph_file_facts VALUES (?, ?, ?, ?)",
                           (snapshot_id, path, file["blob_id"], json.dumps(facts[path], separators=(",", ":"))))
    nodes = {}
    edges = {}

    def provenance(path=None, line=None, source="git_commit"):
        result = {"source": source, "commit_sha": snapshot["commit_sha"], "snapshot_id": snapshot_id}
        if path is not None:
            result.update(path=path, blob_id=files[path]["blob_id"])
        if line is not None:
            result.update(line_start=line, line_end=line)
        return result

    def anchor(path, line=None, symbol=None):
        candidates = [item for item in chunks[path] if (line is None or item["line_start"] <= line <= item["line_end"])
                      and (symbol is None or item["symbol"] == symbol)]
        if not candidates and symbol is not None:
            return anchor(path, line)
        return min(candidates, key=lambda item: (item["line_end"] - item["line_start"], item["id"]))["id"] if candidates else None

    def node(kind, key, name, path=None, symbol=None, start=None, end=None, properties=None):
        identity = stable_id("graph_node", snapshot_id, kind, key)
        nodes[identity] = {"id": identity, "kind": kind, "name": name, "path": path, "symbol": symbol,
                           "line_start": start, "line_end": end,
                           "evidence_id": anchor(path, start, symbol) if path else None,
                           "provenance": provenance(path, start, "python_ast" if start else "git_tree" if path else "git_commit"),
                           "properties": properties or {}}
        return identity

    def edge(source, target, kind, path=None, line=None, inference=False):
        if not source or not target or source == target:
            return
        identity = stable_id("graph_edge", snapshot_id, source, target, kind, path or "", line or 0)
        edges[identity] = (identity, snapshot_id, source, target, kind, anchor(path, line) if path else None,
                           json.dumps(provenance(path, line, "static_reference" if path else "git_commit")), int(inference))

    repository_node = node("repository", snapshot["repository_id"], snapshot["root"])
    commit_node = node("commit", snapshot["commit_sha"], snapshot["commit_sha"])
    edge(repository_node, commit_node, "contains")
    for branch in snapshot["stats"].get("local_branches", []):
        branch_node = node("branch", branch, branch, properties={"observation": "contains selected commit at ingestion"})
        edge(repository_node, branch_node, "contains")
        edge(branch_node, commit_node, "contains")
    file_nodes = {}
    module_nodes = {}
    modules = defaultdict(list)
    definitions = defaultdict(list)
    definition_facts = {}
    for path, file in files.items():
        file_nodes[path] = node("file", path, path, path, properties={"status": file["status"]})
        edge(repository_node, file_nodes[path], "contains", path)
        if file["language"] == "python" and file["text"] is not None:
            module = module_name(path)
            modules[module].append(path)
            module_nodes[path] = node("module", path, module, path)
            edge(file_nodes[path], module_nodes[path], "defines", path)
            for item in facts[path]["definitions"]:
                kind = "test" if _is_test(path) and item["kind"] == "function" else item["kind"]
                identity = node(kind, [path, item["name"], item["line_start"]], item["name"], path,
                                item["name"], item["line_start"], item["line_end"])
                definitions[path, item["name"]].append(identity)
                definition_facts[identity] = item
                edge(module_nodes[path], identity, "defines", path, item["line_start"])
        elif path.endswith(".md") and file["text"] is not None:
            identity = node("document", path, path, path)
            edge(file_nodes[path], identity, "defines", path)
        elif path.endswith((".toml", ".yaml", ".yml", ".json", ".ini", ".cfg")):
            identity = node("configuration", path, path, path)
            edge(file_nodes[path], identity, "defines", path)

    def unique(values):
        return values[0] if len(values) == 1 else None

    def owner_node(path, owner):
        return unique(definitions[path, owner]) if owner else module_nodes.get(path)

    def module_path(name):
        if name in modules:
            return unique(modules[name])
        matches = [path for module, paths in modules.items() if module.endswith("." + name) for path in paths]
        return unique(matches)

    def imported_target(path, item, seen=None):
        seen = set() if seen is None else seen
        key = (path, item["module"], item["member"], item["level"])
        if key in seen:
            return None
        seen.add(key)
        name = item["module"]
        if item["level"]:
            package = module_name(path).split(".")
            if not path.endswith("/__init__.py"):
                package = package[:-1]
            if item["level"] > len(package):
                return None
            name = ".".join(package[:len(package) - item["level"] + 1] + ([name] if name else []))
        target_path = module_path(name)
        if item["member"]:
            if target_path and (identity := unique(definitions[target_path, item["member"]])):
                return identity
            exported = [value for value in facts.get(target_path, {}).get("imports", [])
                        if not value["owner"] and value["local"] == item["member"]]
            if len(exported) == 1:
                return imported_target(target_path, exported[0], seen)
            child = module_path(name + "." + item["member"])
            return module_nodes.get(child)
        return module_nodes.get(target_path)

    def scopes(owner):
        parts = owner.split(".") if owner else []
        return [".".join(parts[:length]) for length in range(len(parts), -1, -1)]

    class_bases = defaultdict(list)

    def member(identity, suffix, seen=None):
        current = nodes[identity]
        seen = set() if seen is None else seen
        key = (identity, suffix)
        if key in seen:
            return None
        seen.add(key)
        if current["kind"] == "module":
            direct = unique(definitions[current["path"], suffix])
            if direct:
                return direct
            first, _, rest = suffix.partition(".")
            imported = [item for item in facts[current["path"]]["imports"] if not item["owner"] and item["local"] == first]
            if len(imported) == 1:
                target = imported_target(current["path"], imported[0])
                return member(target, rest, seen) if target and rest else target
            child = module_path(current["name"] + "." + first)
            return member(module_nodes[child], rest, seen) if child and rest else module_nodes.get(child)
        direct = unique(definitions[current["path"], current["symbol"] + "." + suffix])
        if direct:
            return direct
        if len(class_bases[identity]) != 1:
            return None
        return member(class_bases[identity][0], suffix, seen)

    def resolve(path, owner, expression):
        if not expression:
            return None
        first, _, rest = expression.partition(".")
        if first in ("self", "cls") and rest:
            for scope in scopes(owner):
                function = owner_node(path, scope)
                if function and definition_facts.get(function, {}).get("receiver") == first:
                    container = scope.rsplit(".", 1)[0] if "." in scope else ""
                    parent_class = owner_node(path, container)
                    if parent_class and nodes[parent_class]["kind"] in ("class", "interface"):
                        if sum(binding["owner"] == scope and binding["name"] == first for binding in facts[path]["bindings"]) > 1:
                            return None
                        return member(parent_class, rest)
                    return None
            return None
        current = owner_node(path, owner)
        inside_function = current and nodes[current]["kind"] in ("function", "test")
        for scope in scopes(owner):
            scope_node = owner_node(path, scope)
            if inside_function and scope_node and nodes[scope_node]["kind"] in ("class", "interface"):
                continue
            if any(binding["owner"] == scope and binding["name"] == first for binding in facts[path]["bindings"]):
                return None
            local = ".".join([scope, first]) if scope else first
            identity = unique(definitions[path, local])
            if identity:
                return member(identity, rest) if rest else identity
            imports = [item for item in facts[path]["imports"] if item["owner"] == scope and item["local"] == first]
            if imports:
                identity = imported_target(path, imports[0]) if len(imports) == 1 else None
                return member(identity, rest) if identity and rest else identity
        return None

    unresolved_imports = 0
    unresolved_calls = 0
    for path, file_facts in facts.items():
        for item in file_facts["imports"]:
            target = imported_target(path, item)
            if target:
                edge(owner_node(path, item["owner"]), target, "imports", path, item["line"])
            else:
                unresolved_imports += 1
        for item in file_facts["definitions"]:
            identity = unique(definitions[path, item["name"]])
            for base in item["bases"]:
                resolved = resolve(path, item["name"].rsplit(".", 1)[0] if "." in item["name"] else "", base)
                if identity and resolved and nodes[resolved]["kind"] in ("class", "interface"):
                    class_bases[identity].append(resolved)
                    edge(identity, resolved, "implements", path, item["line_start"])
            if "." in item["name"]:
                container = unique(definitions[path, item["name"].rsplit(".", 1)[0]])
                edge(container, identity, "defines", path, item["line_start"])
    # Resolve calls after every class base has been linked, independent of file order.
    for path, file_facts in facts.items():
        for call in file_facts["calls"]:
            target = resolve(path, call["owner"], call["expression"])
            if target:
                source = owner_node(path, call["owner"])
                edge(source, target, "calls", path, call["line"])
                if _is_test(path):
                    edge(source, target, "tests", path, call["line"])
            else:
                unresolved_calls += 1
        for config in file_facts["configuration"]:
            identity = node("configuration", [path, config["key"], config["line"]], config["key"], path,
                            start=config["line"], end=config["line"])
            edge(owner_node(path, config["owner"]), identity, "depends_on", path, config["line"])
    by_name = defaultdict(list)
    for identity, item in nodes.items():
        if item["symbol"]:
            by_name[item["symbol"]].append(identity)
    for path, file in files.items():
        if not path.endswith(".md") or file["text"] is None:
            continue
        doc = stable_id("graph_node", snapshot_id, "document", path)
        for line, text in enumerate(file["text"].splitlines(), 1):
            for reference in set(re.findall(r"(?<![\w.])[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+", text)):
                target = unique(by_name[reference])
                if target:
                    edge(doc, target, "documents", path, line, inference=True)
    try:
        git = GitRepository(snapshot["root"])
        changes = git.changed_files(commit["parents"][0], snapshot["commit_sha"]) if commit["parents"] else [{"path": path} for path in files]
        for change in changes:
            if change["path"] in file_nodes:
                edge(commit_node, file_nodes[change["path"]], "modifies", change["path"])
        changes_available = True
    except RepoLensError:
        changes = []
        changes_available = False
    if len(nodes) > 100000 or len(edges) > 300000:
        raise RepoLensError("Code graph exceeds its bounded node/edge limits; choose a smaller repository.")
    for item in nodes.values():
        connection.execute("INSERT INTO graph_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            item["id"], snapshot_id, item["kind"], item["name"], item["path"], item["symbol"],
            item["line_start"], item["line_end"], item["evidence_id"], json.dumps(item["provenance"]), json.dumps(item["properties"])))
    connection.executemany("INSERT INTO graph_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?)", edges.values())
    stats = {"nodes": len(nodes), "edges": len(edges), "reused_fact_files": reused,
             "parsed_fact_files": len(files) - reused, "base_snapshot_id": parent["id"] if parent else None,
             "unresolved_calls": unresolved_calls, "unresolved_imports": unresolved_imports,
             "parse_errors": sum(item["parse_error"] for item in facts.values()),
             "commit_changes_available": changes_available,
             "base_commit_sha": commit["parents"][0] if commit["parents"] else None,
             "deleted_paths": [item["path"] for item in changes if item.get("status") == "D"]}
    connection.execute("INSERT INTO graph_builds VALUES (?, ?, ?)", (snapshot_id, GRAPH_POLICY, json.dumps(stats)))
    return stats
