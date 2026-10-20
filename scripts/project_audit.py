"""Read-only size, static dependency and local Markdown-link inventory."""

import argparse
import ast
from collections import defaultdict
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def inspect_project(root: Path) -> dict:
    importers = defaultdict(list)
    for path in sorted((root / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                importers[node.module].append(path.relative_to(root).as_posix())
    modules = []
    for path in sorted((root / "src" / "repolens").rglob("*.py")):
        if "fixtures" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        functions = [node for node in ast.walk(tree)
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        module = ".".join(path.relative_to(root / "src").with_suffix("").parts)
        dependencies = {node.module for node in ast.walk(tree)
                        if isinstance(node, ast.ImportFrom) and node.module
                        and node.module.startswith("repolens")}
        modules.append({
            "path": path.relative_to(root).as_posix(), "lines": len(text.splitlines()),
            "function_count": len(functions), "imports": sorted(dependencies),
            "direct_test_importers": sorted(set(importers[module])),
            "largest_functions": sorted([
                {"name": node.name, "line": node.lineno,
                 "span_lines": node.end_lineno - node.lineno + 1}
                for node in functions
            ], key=lambda item: (-item["span_lines"], item["line"]))[:3],
        })
    documents = [root / name for name in ("README.md", "CONTRIBUTING.md", "SECURITY.md")]
    documents.extend(sorted((root / "docs").rglob("*.md")))
    broken = []
    link_count = 0
    for path in documents:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        # This checks common inline links, not full CommonMark or remote URLs.
        text = re.sub(r"(?ms)^(```|~~~).*?^\1[^\n]*$", "", text)
        for target in re.findall(r"\[[^\]\n]*\]\(([^)\n]+)\)", text):
            target = target.strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            link_count += 1
            local = path.parent / unquote(parsed.path)
            if not local.exists():
                broken.append({"document": path.relative_to(root).as_posix(), "target": target})
    return {
        "schema_version": "repolens.project-audit.v1",
        "modules": sorted(modules, key=lambda item: (-item["lines"], item["path"])),
        "local_link_count": link_count, "broken_links": broken,
        "limits": "Static imports are not runtime coverage; line spans are not complexity. "
                  "Inline local-link existence only; no anchor or remote-link validation.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-links", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = inspect_project(ROOT)
    if args.output:
        with args.output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(report, stream, ensure_ascii=True, indent=2)
            stream.write("\n")
    print(json.dumps({"modules": len(report["modules"]), "local_links": report["local_link_count"],
                      "broken_links": report["broken_links"],
                      "largest_modules": [{"path": item["path"], "lines": item["lines"]}
                                          for item in report["modules"][:5]]},
                     ensure_ascii=True, indent=2))
    return 1 if args.check_links and report["broken_links"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
