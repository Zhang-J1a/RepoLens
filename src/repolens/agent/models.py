"""Budget and metadata-only trace contracts for the controlled agent."""

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
import re
import time
import uuid

from repolens.domain import RepoLensError


class AgentStop(RepoLensError):
    """A classified stop whose message never includes provider/repository data."""


@dataclass(frozen=True)
class AgentBudget:
    max_steps: int = 8
    max_model_calls: int = 6
    max_total_tokens: int = 32000
    max_results_per_call: int = 8
    max_total_results: int = 64
    context_tokens: int = 2400
    output_tokens: int = 768
    timeout_seconds: float = 120.0

    def __post_init__(self):
        ranges = {
            "max_steps": (1, 32), "max_model_calls": (1, 16),
            "max_total_tokens": (1, 200000), "max_results_per_call": (1, 40),
            "max_total_results": (1, 500), "context_tokens": (1, 16000),
            "output_tokens": (1, 8192),
        }
        for name, (minimum, maximum) in ranges.items():
            value = getattr(self, name)
            if type(value) is not int or not minimum <= value <= maximum:
                raise RepoLensError(f"Agent {name} must be an integer between {minimum} and {maximum}.")
        value = self.timeout_seconds
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or not 0.1 <= value <= 600):
            raise RepoLensError("Agent timeout_seconds must be finite and between 0.1 and 600.")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def _redact(value):
    if isinstance(value, str):
        value = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", value)
        return re.sub(r"(?i)(api[_ -]?key|authorization|password|secret)(\s*[:=]\s*)\S+",
                      r"\1\2[REDACTED]", value)[:4096]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


@dataclass
class AgentTrace:
    budget: AgentBudget
    question: str
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started: float = field(default_factory=time.monotonic)
    events: list[dict] = field(default_factory=list)
    steps: int = 0
    model_calls: int = 0
    reserved_tokens: int = 0
    result_count: int = 0
    usage: dict = field(default_factory=dict)
    on_event: object = field(default=None, repr=False, compare=False)

    @property
    def remaining_seconds(self):
        return max(0.0, self.budget.timeout_seconds - (time.monotonic() - self.started))

    def check_deadline(self):
        if self.remaining_seconds <= 0:
            raise AgentStop("deadline_exceeded")

    def event(self, state, status, *, name=None, inputs=None, outputs=None, elapsed_ms=0, error=None):
        self.events.append(_redact({
            "sequence": len(self.events) + 1, "task_id": self.task_id, "trace_id": self.trace_id,
            "state": state, "name": name, "status": status,
            "input": inputs or {}, "output": outputs or {}, "error_code": error,
            "elapsed_ms": max(0, round(elapsed_ms)),
        }))
        if self.on_event is not None:
            # UI observers cannot change the analysis outcome or permission boundary.
            try:
                self.on_event(json.loads(json.dumps(self.events[-1])))
            except Exception:
                pass

    def to_dict(self):
        return {
            "schema_version": "repolens.agent-trace.v1", "task_id": self.task_id,
            "trace_id": self.trace_id, "input": _redact({"question": self.question}),
            "budget": asdict(self.budget),
            "consumed": {"steps": self.steps, "model_calls": self.model_calls,
                         "reserved_tokens": self.reserved_tokens, "results": self.result_count,
                         "provider_usage": self.usage,
                         "duration_ms": round((time.monotonic() - self.started) * 1000)},
            "events": list(self.events),
        }
