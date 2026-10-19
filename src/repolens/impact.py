"""Bounded commit impact analysis built from local Git diffs and snapshots."""

from collections.abc import Mapping
import re
from typing import Any
import uuid

from repolens.answer import (
    answer_schema_document,
    abstained_answer,
    validate_provider_output,
)
from repolens.context import EvidenceContextPacker
from repolens.domain import RepoLensError
from repolens.git import GitRepository
from repolens.index import IndexStore
from repolens.ingestion import ingest_or_reuse
from repolens.provider import Provider, ProviderRequest
from repolens.relationships import find_call_relations


IMPACT_SCHEMA_VERSION = "repolens.impact.v2"
MAX_CHANGED_FILES = 500
MAX_SYMBOLS_PER_FILE = 100
MAX_RELATED_EVIDENCE = 40
MAX_RELATED_HISTORY = 20
MAX_RELATION_TARGETS = 40
RISK_SEVERITIES = ("low", "medium", "high", "blocking")
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def _path_category(path: str) -> str:
    lower = path.lower()
    name = lower.rsplit("/", 1)[-1]
    if (
        name.startswith("test_")
        or name.endswith("_test.py")
        or "/test/" in f"/{lower}/"
        or "/tests/" in f"/{lower}/"
    ):
        return "test"
    if (
        lower.endswith((".md", ".markdown"))
        or name.startswith("readme")
        or "/docs/" in f"/{lower}/"
    ):
        return "documentation"
    if lower.endswith((".toml", ".yaml", ".yml", ".json", ".ini", ".cfg", ".conf")):
        return "configuration"
    return "source"


def _ranges_overlap(start: int, count: int, line_start: int, line_end: int) -> bool:
    if count == 0:
        return line_start <= start <= line_end + 1
    end = start + count - 1
    return start <= line_end and line_start <= end


def _symbol_evidence(store: IndexStore, snapshot_id: str, path: str, line_start: int, line_end: int) -> dict | None:
    try:
        chunks = store.chunks_for_path(snapshot_id, path, limit=100)
    except RepoLensError:
        return None
    candidates = [
        chunk for chunk in chunks
        if chunk["line_start"] <= line_start and line_end <= chunk["line_end"]
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda chunk: (chunk["line_end"] - chunk["line_start"], chunk["line_start"]))


def _symbol_changes(store: IndexStore, change: Mapping[str, Any], base_snapshot: str, head_snapshot: str) -> list[dict[str, Any]]:
    path = str(change["path"])
    status = str(change["status"])
    base_symbols = {item["name"]: item for item in store.symbols(base_snapshot, path)}
    head_symbols = {item["name"]: item for item in store.symbols(head_snapshot, path)}
    hunks = tuple(change["hunks"])
    names = []
    if status in ("A", "C", "R"):
        names = [(name, "added", head_symbols[name]) for name in sorted(head_symbols)]
    elif status == "D":
        names = [(name, "removed", base_symbols[name]) for name in sorted(base_symbols)]
    else:
        for name in sorted(set(base_symbols) | set(head_symbols)):
            if name not in base_symbols:
                names.append((name, "added", head_symbols[name]))
                continue
            if name not in head_symbols:
                names.append((name, "removed", base_symbols[name]))
                continue
            old = base_symbols[name]
            new = head_symbols[name]
            old_hit = any(
                _ranges_overlap(hunk["old_start"], hunk["old_count"], old["line_start"], old["line_end"])
                for hunk in hunks
            )
            new_hit = any(
                _ranges_overlap(hunk["new_start"], hunk["new_count"], new["line_start"], new["line_end"])
                for hunk in hunks
            )
            if old_hit or new_hit:
                names.append((name, "modified", new))
    results = []
    for name, change_kind, symbol in names[:MAX_SYMBOLS_PER_FILE]:
        snapshot_id = base_snapshot if change_kind == "removed" else head_snapshot
        evidence = _symbol_evidence(store, snapshot_id, path, symbol["line_start"], symbol["line_end"])
        results.append({
            "name": name,
            "kind": symbol["kind"],
            "change": change_kind,
            "line_start": symbol["line_start"],
            "line_end": symbol["line_end"],
            "snapshot": "base" if change_kind == "removed" else "head",
            "evidence_id": evidence["evidence_id"] if evidence else None,
            "evidence_snapshot_id": evidence["snapshot_id"] if evidence else snapshot_id,
            "evidence_commit_sha": evidence["commit_sha"] if evidence else None,
        })
    return results


def _is_test(path: str) -> bool:
    return _path_category(path) == "test"


def _is_documentation(path: str) -> bool:
    return _path_category(path) == "documentation"


def _evidence_key(item: Mapping[str, Any]) -> tuple[str, str]:
    return str(item["snapshot_id"]), str(item["evidence_id"])


def _add_evidence(target: list[dict[str, Any]], seen: set[tuple[str, str]], items) -> None:
    for item in items:
        if not isinstance(item.get("text"), str) or not item["text"].strip():
            continue
        key = _evidence_key(item)
        if key in seen:
            continue
        seen.add(key)
        target.append(dict(item))


def _evidence_view(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in (
            "evidence_id", "snapshot_id", "commit_sha", "path", "symbol",
            "kind", "line_start", "line_end", "text",
        )
        if key in item
    }


def _history_view(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: item[key]
        for key in (
            "history_id", "snapshot_id", "commit_sha", "parents", "author", "authored_at", "message",
            "history_score",
        )
        if key in item
    }


def _relation_view(item: Mapping[str, Any]) -> dict[str, Any]:
    evidence = item["evidence"]
    return {
        "relation": item["relation"],
        "target_symbol": item["target_symbol"],
        "path": item["path"],
        "symbol": item["symbol"],
        "line_start": item["line_start"],
        "line_end": item["line_end"],
        "evidence_id": evidence["evidence_id"],
        "snapshot_id": evidence["snapshot_id"],
        "commit_sha": evidence["commit_sha"],
    }


def _related_evidence(store: IndexStore, snapshot_id: str, changed_files: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    queries: list[str] = []
    for change in changed_files:
        for symbol in change["symbols"][:8]:
            queries.append(str(symbol["name"]))
        if not change["symbols"]:
            path = str(change["path"])
            queries.append(path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
    for query in dict.fromkeys(queries):
        try:
            results = store.search(query, snapshot_id, limit=10)
        except RepoLensError:
            continue
        for item in results:
            if _is_test(item["path"]) or _is_documentation(item["path"]):
                _add_evidence(related, seen, (item,))
                if len(related) >= MAX_RELATED_EVIDENCE:
                    return related
    return related


def _related_history(store: IndexStore, snapshot_id: str, changed_files: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    seen: set[str] = set()
    queries: list[str] = []
    for change in changed_files:
        path = str(change["path"])
        queries.append(path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
        queries.extend(str(symbol["name"]) for symbol in change["symbols"][:4])
    for query in dict.fromkeys(queries):
        try:
            results = store.search_history(query, snapshot_id, limit=5)
        except RepoLensError:
            continue
        for item in results:
            if item["commit_sha"] in seen:
                continue
            seen.add(item["commit_sha"])
            related.append(dict(item))
            if len(related) >= MAX_RELATED_HISTORY:
                return related
    if not related:
        try:
            related.extend(store.history(snapshot_id, limit=MAX_RELATED_HISTORY))
        except RepoLensError:
            pass
    return related


def _rule_risks(changed_files: list[Mapping[str, Any]], related_tests: list[Mapping[str, Any]], evidence: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    test_paths = {item["path"] for item in related_tests}
    risks = []
    for change in changed_files:
        path = str(change["path"])
        direct_ids = [item["evidence_id"] for item in evidence if item["path"] == path]
        if change["status"] == "D" and _path_category(path) == "source":
            risks.append({
                "severity": "high",
                "reason": "源文件被删除，调用方或运行时入口可能仍然依赖它。",
                "inference": True,
                "path": path,
                "evidence_ids": direct_ids,
            })
        if change["status"] == "D" and _path_category(path) == "configuration":
            risks.append({
                "severity": "blocking",
                "reason": "配置文件被删除，启动或部署流程可能无法读取必需配置。",
                "inference": True,
                "path": path,
                "evidence_ids": direct_ids,
            })
        if _path_category(path) == "source" and change["symbols"] and not test_paths:
            risks.append({
                "severity": "medium",
                "reason": "源码 symbol 发生变化，但当前 snapshot 没有检索到相关测试 evidence。",
                "inference": True,
                "path": path,
                "evidence_ids": direct_ids,
            })
        if _path_category(path) == "configuration":
            risks.append({
                "severity": "medium",
                "reason": "配置文件发生变化，需要确认加载、校验和部署环境与新格式一致。",
                "inference": True,
                "path": path,
                "evidence_ids": direct_ids,
            })
        if _path_category(path) in ("documentation", "test") and change["status"] in ("A", "M", "C", "R"):
            risks.append({
                "severity": "low",
                "reason": "测试或文档发生变化，需确认说明与当前实现仍然一致。",
                "inference": True,
                "path": path,
                "evidence_ids": direct_ids,
            })
    return risks


def _suggested_tests(
    changed_files: list[Mapping[str, Any]],
    related_tests: list[Mapping[str, Any]],
    evidence: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    suggestions = []
    related_names = ", ".join(sorted({item["path"] for item in related_tests})[:3])
    for change in changed_files:
        source_symbols = [item["name"] for item in change["symbols"] if item["change"] != "removed"]
        if source_symbols:
            target = ", ".join(source_symbols[:4])
            text = f"为 {change['path']} 中的 {target} 运行或补充回归测试。"
        elif _path_category(str(change["path"])) == "configuration":
            text = f"校验 {change['path']} 的配置加载、格式校验和启动路径。"
        else:
            text = f"为 {change['path']} 的变更增加针对性回归检查。"
        if related_names:
            text += f" 可优先检查 {related_names}。"
        evidence_ids = [item["evidence_id"] for item in related_tests[:5]]
        evidence_ids.extend(
            item["evidence_id"] for item in evidence
            if item["path"] == change["path"] and item["evidence_id"] not in evidence_ids
        )
        suggestions.append({
            "text": text,
            "path": change["path"],
            "inference": True,
            "evidence_ids": evidence_ids[:8],
        })
    return suggestions


def _model_answer(
    provider: Provider,
    question: str,
    evidence: list[Mapping[str, Any]],
    *,
    context_tokens: int,
    output_tokens: int,
    trace_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    context = EvidenceContextPacker(context_tokens).pack(evidence)
    if not context.items:
        answer = abstained_answer(question, "影响分析 evidence 无法放入当前上下文预算。", trace_id=trace_id)
        return answer.to_dict(), {"context": context.to_dict(), "provider_calls": 0}
    response = provider.generate(ProviderRequest(
        question=question,
        context=context.rendered,
        evidence_ids=context.citation_ids,
        output_schema=answer_schema_document(),
        max_output_tokens=output_tokens,
        metadata={"trace_id": trace_id, "task": "impact"},
    ))
    answer = validate_provider_output(
        response.output,
        context,
        question,
        provider=response.provider,
        model=response.model,
        trace_id=trace_id,
    )
    return answer.to_dict(), {
        "context": context.to_dict(),
        "provider_calls": 1,
        "provider": response.provider,
        "model": response.model,
        "usage": dict(response.usage),
        "attempts": response.attempts,
        "provider_request_id": response.request_id,
    }


def build_impact_report(
    store: IndexStore,
    git: GitRepository,
    base_sha: str,
    head_sha: str,
    base_snapshot: str,
    head_snapshot: str,
    *,
    provider: Provider | None = None,
    context_tokens: int = 2400,
    output_tokens: int = 768,
    question: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic impact report and optionally add one model pass."""

    trace_id = uuid.uuid4().hex
    raw_changes = git.changed_files(base_sha, head_sha)
    if len(raw_changes) > MAX_CHANGED_FILES:
        raise RepoLensError(f"Impact analysis supports at most {MAX_CHANGED_FILES} changed files per run.")
    changed_files: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    evidence_seen: set[tuple[str, str]] = set()
    for raw_change in raw_changes:
        path = str(raw_change["path"])
        change = dict(raw_change)
        change["category"] = _path_category(path)
        change["hunks"] = git.diff_hunks(base_sha, head_sha, path)
        change["symbols"] = _symbol_changes(store, change, base_snapshot, head_snapshot)
        for symbol in change["symbols"]:
            if symbol["evidence_id"]:
                _add_evidence(
                    evidence,
                    evidence_seen,
                    (store.evidence(symbol["evidence_id"], symbol["evidence_snapshot_id"]),),
                )
        if change["status"] == "D":
            _add_evidence(evidence, evidence_seen, store.chunks_for_path(base_snapshot, path, limit=5))
        else:
            _add_evidence(evidence, evidence_seen, store.chunks_for_path(head_snapshot, path, limit=5))
        changed_files.append(change)

    related = _related_evidence(store, head_snapshot, changed_files)
    related_history = _related_history(store, head_snapshot, changed_files)
    relation_targets = [
        str(symbol["name"])
        for change in changed_files
        if change["category"] == "source"
        for symbol in change["symbols"]
        if symbol["change"] != "removed"
    ][:MAX_RELATION_TARGETS]
    relations = find_call_relations(store, head_snapshot, relation_targets)
    _add_evidence(evidence, evidence_seen, related)
    _add_evidence(evidence, evidence_seen, (item["evidence"] for item in (*relations["callers"], *relations["callees"])))
    related_tests = [item for item in related if _is_test(item["path"])]
    related_docs = [item for item in related if _is_documentation(item["path"])]
    related_configuration = [
        _evidence_view(item)
        for item in evidence
        if any(change["path"] == item["path"] and change["category"] == "configuration" for change in changed_files)
    ]
    risks = _rule_risks(changed_files, related_tests, evidence)
    if any(risk["severity"] not in RISK_SEVERITIES for risk in risks):
        raise RepoLensError("Impact rule produced an unsupported risk severity.")
    suggestions = _suggested_tests(changed_files, related_tests, evidence)
    unknowns = []
    head_stats = store.snapshot(head_snapshot)["stats"]
    for diagnostic in head_stats.get("diagnostics", []):
        unknowns.append(f"head snapshot 的 {diagnostic['path']} 未能完整解析：{diagnostic['code']}。")
    if not related_tests and any(item["category"] == "source" for item in changed_files):
        unknowns.append("当前 head snapshot 未检索到相关测试 evidence，不能据此断言不存在测试。")
    if not related_docs and changed_files:
        unknowns.append("当前 head snapshot 未检索到与变化 symbol 直接匹配的文档 evidence。")

    report: dict[str, Any] = {
        "schema_version": IMPACT_SCHEMA_VERSION,
        "status": "partial" if unknowns else "complete",
        "trace_id": trace_id,
        "repository": str(git.root),
        "base": {"commit_sha": base_sha, "snapshot_id": base_snapshot},
        "head": {"commit_sha": head_sha, "snapshot_id": head_snapshot},
        "summary": f"比较 {base_sha[:12]} 到 {head_sha[:12]}，发现 {len(changed_files)} 个变更文件。",
        "changed_files": changed_files,
        "related_tests": [_evidence_view(item) for item in related_tests],
        "related_docs": [_evidence_view(item) for item in related_docs],
        "related_configuration": related_configuration,
        "related_history": [_history_view(item) for item in related_history],
        "related_callers": [_relation_view(item) for item in relations["callers"]],
        "related_callees": [_relation_view(item) for item in relations["callees"]],
        "risks": risks,
        "suggested_tests": suggestions,
        "evidence": [_evidence_view(item) for item in evidence],
        "unknowns": unknowns,
        "telemetry": {"provider_calls": 0},
    }
    if provider is not None and evidence:
        model_question = question or (
            "分析这个本地 Git commit 范围的代码影响。说明变更涉及哪些文件和 symbol、相关测试/文档、"
            "潜在风险与建议测试；只能引用提供的 evidence，不确定的内容放入 unknowns。"
        )
        model_answer, telemetry = _model_answer(
            provider,
            model_question,
            evidence,
            context_tokens=context_tokens,
            output_tokens=output_tokens,
            trace_id=trace_id,
        )
        report["model_answer"] = model_answer
        report["telemetry"] = telemetry | {"trace_id": trace_id}
    return report


def render_impact_markdown(report: Mapping[str, Any]) -> str:
    """Render the structured impact envelope without reinterpreting its facts."""

    def clean(value: object) -> str:
        return str(value).replace("\r", " ").replace("\n", " ").strip()

    lines = [
        "# RepoLens Impact Report",
        "",
        f"- Status: `{clean(report.get('status', 'unknown'))}`",
        f"- Trace: `{clean(report.get('trace_id', ''))}`",
        f"- Base: `{clean(report.get('base', {}).get('commit_sha', ''))}`",
        f"- Head: `{clean(report.get('head', {}).get('commit_sha', ''))}`",
        "",
        f"## Summary\n\n{clean(report.get('summary', ''))}",
        "",
        "## Changed Files",
        "",
    ]
    for change in report.get("changed_files", ()):
        lines.append(f"- `{clean(change.get('status', ''))}` `{clean(change.get('path', ''))}` ({clean(change.get('category', ''))})")
        for symbol in change.get("symbols", ()):
            lines.append(
                f"  - `{clean(symbol.get('change', ''))}` `{clean(symbol.get('name', ''))}` "
                f"({clean(symbol.get('line_start', ''))}-{clean(symbol.get('line_end', ''))})"
            )
    for title, key in (("Related Callers", "related_callers"), ("Related Callees", "related_callees")):
        lines.extend(("", f"## {title}", ""))
        entries = report.get(key, ())
        if not entries:
            lines.append("- None found")
        for item in entries:
            lines.append(
                f"- `{clean(item.get('path', ''))}:{clean(item.get('line_start', ''))}-"
                f"{clean(item.get('line_end', ''))}` `{clean(item.get('symbol', ''))}` "
                f"→ `{clean(item.get('target_symbol', ''))}` `{clean(item.get('evidence_id', ''))}`"
            )
    for title, key, label in (
        ("Related Tests", "related_tests", "evidence"),
        ("Related Documentation", "related_docs", "evidence"),
        ("Related Configuration", "related_configuration", "evidence"),
    ):
        lines.extend(("", f"## {title}", ""))
        entries = report.get(key, ())
        if not entries:
            lines.append("- None found")
        for item in entries:
            lines.append(
                f"- `{clean(item.get('path', ''))}:{clean(item.get('line_start', ''))}-"
                f"{clean(item.get('line_end', ''))}` `{clean(item.get('evidence_id', ''))}`"
            )
    lines.extend(("", "## Related History", ""))
    history = report.get("related_history", ())
    if not history:
        lines.append("- None found")
    for item in history:
        lines.append(f"- `{clean(item.get('commit_sha', ''))}` {clean(item.get('message', ''))}")
    lines.extend(("", "## Risks", ""))
    risks = report.get("risks", ())
    if not risks:
        lines.append("- None found")
    for risk in risks:
        lines.append(
            f"- **{clean(risk.get('severity', ''))}** {clean(risk.get('reason', ''))} "
            f"(`{clean(risk.get('path', ''))}`, inference=`{clean(risk.get('inference', ''))}`)"
        )
    lines.extend(("", "## Suggested Tests", ""))
    for suggestion in report.get("suggested_tests", ()):
        lines.append(f"- {clean(suggestion.get('text', ''))}")
    if not report.get("suggested_tests"):
        lines.append("- None")
    lines.extend(("", "## Unknowns", ""))
    for unknown in report.get("unknowns", ()):
        lines.append(f"- {clean(unknown)}")
    if not report.get("unknowns"):
        lines.append("- None")
    return "\n".join(lines) + "\n"


def analyze_impact(
    repository: str,
    directory,
    base_ref: str,
    head_ref: str,
    *,
    provider: Provider | None = None,
    context_tokens: int = 2400,
    output_tokens: int = 768,
    question: str | None = None,
    with_graph: bool = False,
) -> dict[str, Any]:
    """Index two local commits and return a snapshot-pinned impact report."""

    git = GitRepository(repository)
    base = git.commit(base_ref)
    head = git.commit(head_ref)
    base_ingestion = ingest_or_reuse(repository, directory, base.sha)
    head_ingestion = ingest_or_reuse(repository, directory, head.sha)
    with IndexStore(directory) as store:
        report = build_impact_report(
            store,
            git,
            base.sha,
            head.sha,
            base_ingestion["snapshot_id"],
            head_ingestion["snapshot_id"],
            provider=provider,
            context_tokens=context_tokens,
            output_tokens=output_tokens,
            question=question,
        )
        if with_graph:
            from repolens.graph.query import GraphStore

            graph = GraphStore(store).for_paths(head_ingestion["snapshot_id"],
                                                [change["path"] for change in report["changed_files"] if change["status"] != "D"])
            report["graph"] = graph
            deleted = [change["path"] for change in report["changed_files"] if change["status"] == "D"]
            if deleted:
                report["graph_base"] = GraphStore(store).for_paths(base_ingestion["snapshot_id"], deleted)
            priorities = {}
            for node in graph["nodes"]:
                priorities[node["path"]] = max(priorities.get(node["path"], 0), node["review_priority"])
            for risk in report["risks"]:
                risk["graph_review_priority"] = priorities.get(risk.get("path"), 0)
            report["risks"].sort(key=lambda risk: (-RISK_SEVERITIES.index(risk["severity"]), -risk["graph_review_priority"]))
    report["workflow"] = {
        "repository": str(git.root),
        "base_ref": base_ref,
        "head_ref": head_ref,
        "base_index_action": base_ingestion["index_action"],
        "head_index_action": head_ingestion["index_action"],
    }
    return report
