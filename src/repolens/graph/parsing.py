"""Extract syntax facts without imports, execution, or receiver-name guessing."""

import ast
from pathlib import PurePosixPath


def module_name(path):
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = dotted(node.value)
        return parent + "." + node.attr if parent else None
    return None


class Facts(ast.NodeVisitor):
    def __init__(self):
        self.scope = []
        self.definitions = []
        self.imports = []
        self.calls = []
        self.configuration = []
        self.bindings = []

    @property
    def owner(self):
        return ".".join(self.scope)

    def definition(self, node, kind):
        name = ".".join([*self.scope, node.name])
        item = {"name": name, "kind": kind, "line_start": node.lineno,
                "line_end": node.end_lineno, "bases": [], "receiver": None}
        if isinstance(node, ast.ClassDef):
            item["bases"] = [value for base in node.bases if (value := dotted(base))]
        else:
            parameters = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
            parameters += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
            self.bindings.extend({"owner": name, "name": arg.arg, "line": node.lineno} for arg in parameters)
            if parameters and parameters[0].arg in ("self", "cls") and not any(
                dotted(decorator) == "staticmethod" for decorator in node.decorator_list
            ):
                item["receiver"] = parameters[0].arg
        self.definitions.append(item)
        self.scope.append(node.name)
        for child in node.body:
            self.visit(child)
        self.scope.pop()

    def visit_FunctionDef(self, node):
        self.definition(node, "function")

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self.definition(node, "interface" if any(dotted(base) in ("Protocol", "typing.Protocol", "ABC", "abc.ABC")
                                                for base in node.bases) else "class")

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append({"owner": self.owner, "local": alias.asname or alias.name.split(".")[0],
                                 "module": alias.name if alias.asname else alias.name.split(".")[0],
                                 "member": None, "level": 0, "line": node.lineno})

    def visit_ImportFrom(self, node):
        for alias in node.names:
            if alias.name != "*":
                self.imports.append({"owner": self.owner, "local": alias.asname or alias.name,
                                     "module": node.module or "", "member": alias.name,
                                     "level": node.level, "line": node.lineno})

    def visit_Call(self, node):
        self.calls.append({"owner": self.owner, "expression": dotted(node.func), "line": node.lineno})
        self.generic_visit(node)

    def visit_Subscript(self, node):
        if (isinstance(node.value, ast.Attribute) and node.value.attr == "config"
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str)):
            self.configuration.append({"owner": self.owner, "key": node.slice.value, "line": node.lineno})
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Store):
            self.bindings.append({"owner": self.owner, "name": node.id, "line": node.lineno})


def extract_facts(path, text):
    if not path.endswith(".py") or text is None:
        return {"definitions": [], "imports": [], "calls": [], "configuration": [], "bindings": [], "parse_error": False}
    facts = Facts()
    try:
        facts.visit(ast.parse(text, filename=path))
    except (SyntaxError, RecursionError):
        return {"definitions": [], "imports": [], "calls": [], "configuration": [], "bindings": [], "parse_error": True}
    return {key: getattr(facts, key) for key in ("definitions", "imports", "calls", "configuration", "bindings")} | {"parse_error": False}
