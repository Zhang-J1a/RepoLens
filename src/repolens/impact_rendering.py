"""Render validated impact reports without Git, index or provider operations."""

from collections.abc import Mapping
from typing import Any


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
