"""Host-bound, budgeted evidence tools for an external local MCP client."""

import json
from pathlib import Path
import time

from repolens.agent.execution import execute_bounded
from repolens.agent.models import AgentBudget, AgentStop, digest
from repolens.agent.tools import (
    ToolContext, _validate_snapshot_binding, dispatch_tool, observation,
    tool_catalog, validate_action,
)
from repolens.domain import RepoLensError
from repolens.git import GitRepository
from repolens.index import IndexStore


MAX_RESULT_BYTES = 128 * 1024
MAX_SESSION_BYTES = 1024 * 1024


def _dispatch(context: ToolContext, name: str, arguments: dict) -> tuple[dict, int, int]:
    if name == "get_evidence":
        evidence = None
        with IndexStore(Path(context.directory)) as store:
            root = Path(context.repository).resolve(strict=True)
            for snapshot, sha in ((context.snapshot_id, context.commit_sha),
                                  (context.base_snapshot_id, context.base_sha)):
                if snapshot:
                    _validate_snapshot_binding(store, snapshot, sha, root)
            for snapshot in (context.snapshot_id, context.base_snapshot_id):
                if snapshot:
                    try:
                        evidence = store.evidence(arguments["evidence_id"], snapshot)
                        break
                    except RepoLensError:
                        pass
        if evidence is None:
            raise AgentStop("evidence_not_available")
        result = {"items": [evidence], "evidence": [evidence],
                  "limitations": [], "possibly_truncated": False}
    else:
        result = dispatch_tool(context, name, arguments)
    size = len(json.dumps(result, ensure_ascii=True, allow_nan=False).encode("utf-8"))
    if size > MAX_RESULT_BYTES:
        raise AgentStop("response_byte_limit_exceeded")
    return result, observation(result)["result_count"], size


class AgentContextService:
    """One fixed repository and snapshot pair per session; no ingestion or model."""

    def __init__(self, repository, directory, snapshot_id, *, base_snapshot_id=None, budget=None):
        self.budget = budget or AgentBudget()
        git = GitRepository(repository)
        with IndexStore(Path(directory)) as store:
            head = store.snapshot(snapshot_id)
            _validate_snapshot_binding(store, snapshot_id, head["commit_sha"], git.root)
            base = store.snapshot(base_snapshot_id) if base_snapshot_id else None
            if base:
                _validate_snapshot_binding(store, base_snapshot_id, base["commit_sha"], git.root)
        self.context = ToolContext(str(git.root), str(Path(directory).resolve()), snapshot_id, head["commit_sha"],
                                   base["commit_sha"] if base else None, base_snapshot_id)
        self.binding = {"repository_id": head["repository_id"], "snapshot_id": snapshot_id,
                        "commit_sha": head["commit_sha"], "base_snapshot_id": base_snapshot_id,
                        "base_sha": self.context.base_sha}
        self.started = time.monotonic()
        self.steps = self.results = self.bytes = 0
        self.seen = set()

    def catalog(self) -> list[dict]:
        tools = [{"name": item["name"], "description": item["description"],
                  "inputSchema": item["parameters"],
                  "annotations": {"readOnlyHint": True, "destructiveHint": False,
                                  "idempotentHint": True, "openWorldHint": False}}
                 for item in tool_catalog(self.budget.max_results_per_call)
                 if item["name"] != "list_related_tests"]
        tools.append({
            "name": "get_evidence", "description": "Resolve canonical evidence within the host-selected snapshots.",
            "inputSchema": {"type": "object", "properties": {
                "evidence_id": {"type": "string", "minLength": 1, "maxLength": 4096}},
                "required": ["evidence_id"], "additionalProperties": False},
            "annotations": {"readOnlyHint": True, "destructiveHint": False,
                            "idempotentHint": True, "openWorldHint": False},
        })
        return tools

    def call(self, name, arguments) -> dict:
        try:
            if self.steps >= self.budget.max_steps:
                raise AgentStop("step_budget_exhausted")
            self.steps += 1
            remaining = self.budget.timeout_seconds - (time.monotonic() - self.started)
            if remaining <= 0:
                raise AgentStop("deadline_exceeded")
            if self.results >= self.budget.max_total_results or self.bytes >= MAX_SESSION_BYTES:
                raise AgentStop("session_result_budget_exhausted")
            if name == "get_evidence":
                if (not isinstance(arguments, dict) or set(arguments) != {"evidence_id"}
                        or not isinstance(arguments["evidence_id"], str)
                        or not 1 <= len(arguments["evidence_id"].strip()) <= 4096):
                    raise AgentStop("invalid_tool_arguments")
                normalized = dict(arguments)
            else:
                if not isinstance(name, str) or name == "list_related_tests":
                    raise AgentStop("tool_not_allowed")
                normalized = validate_action(name, arguments, self.budget.max_results_per_call)
            identity = (name, digest(normalized))
            if identity in self.seen:
                raise AgentStop("repeated_tool_call")
            self.seen.add(identity)
            result, count, size = execute_bounded(_dispatch, (self.context, name, normalized), min(15.0, remaining))
            self.results += count
            self.bytes += size
            if self.results > self.budget.max_total_results or self.bytes > MAX_SESSION_BYTES:
                raise AgentStop("session_result_budget_exhausted")
            return {"binding": self.binding, "result": result,
                    "consumed": {"calls": self.steps, "results": self.results, "bytes": self.bytes}}
        except AgentStop as exc:
            return {"binding": self.binding, "error_code": str(exc)}
        except Exception:
            return {"binding": self.binding, "error_code": "tool_failed"}
