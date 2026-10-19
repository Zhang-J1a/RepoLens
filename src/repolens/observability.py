"""Small dependency-free observability primitives for the local V6 service."""

from __future__ import annotations

from collections import defaultdict, deque
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import math
import re
import sys
import threading
import time
import uuid
from typing import Any


_REQUEST_ID: ContextVar[str] = ContextVar("repolens_request_id", default="-")
_SECRET_KEY = re.compile(r"(?i)(api[_ -]?key|authorization|password|secret|token)")
_SECRET_VALUE = re.compile(r"(?i)(?:sk|key|token|bearer)[-_][A-Za-z0-9._-]{8,}")
_ROUTES = frozenset({"/", "/api/health", "/api/settings", "/api/workspaces", "/api/demo", "/api/tasks",
                     "/api/source", "/api/diff", "/api/evaluations", "/api/metrics", "/metrics",
                     "/docs", "/openapi.json", "/analysis", "/graph", "/search", "/traces", "/evaluations"})


def request_id() -> str:
    return _REQUEST_ID.get()


def valid_request_id(value: str | None) -> str:
    if isinstance(value, str) and 1 <= len(value) <= 64 and re.fullmatch(r"[A-Za-z0-9_-]+", value):
        return value
    return uuid.uuid4().hex


def bind_request_id(value: str):
    return _REQUEST_ID.set(value)


def reset_request_id(token) -> None:
    _REQUEST_ID.reset(token)


def normalize_operation(path: str) -> str:
    if path in _ROUTES:
        return path
    if re.fullmatch(r"/api/tasks/[^/]+(?:/(?:events|export))?", path):
        return re.sub(r"(/api/tasks/)[^/]+", r"\1{id}", path)
    if re.fullmatch(r"/api/workspaces/[^/]+", path):
        return "/api/workspaces/{id}"
    if re.fullmatch(r"/traces/[^/]+", path):
        return "/traces/{id}"
    return "/assets/{file}" if path.startswith("/assets/") else "/other"


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SECRET_KEY.search(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return _SECRET_VALUE.sub("[REDACTED]", value)[:4096]
    return value


class JsonLogFormatter(logging.Formatter):
    """Emit metadata-only JSON lines; never include request bodies or source."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id()),
        }
        for name in ("operation", "status_code", "duration_ms", "error_code", "task_id", "trace_id", "error_type"):
            if hasattr(record, name):
                payload[name] = getattr(record, name)
        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__
        return json.dumps(_redact(payload), ensure_ascii=True, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    """Configure the application logger once; library imports remain side effect free."""

    logger = logging.getLogger("repolens")
    if logger.handlers:
        return
    if sys.stderr is None:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonLogFormatter())
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False


class MetricsRegistry:
    """Bounded counters and latency samples suitable for a single local process."""

    def __init__(self, *, max_samples: int = 1024):
        self._lock = threading.RLock()
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._durations: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=max_samples))

    def increment(self, name: str, value: int = 1) -> None:
        if name not in {"tasks_submitted", "tasks_completed", "tasks_failed", "tasks_degraded", "tasks_evicted"}:
            return
        if type(value) is not int or value < 0:
            return
        with self._lock:
            self._counters[name] += value

    def observe_request(self, method: str, operation: str, status_code: int, duration_ms: float) -> None:
        method = method.upper() if method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "OTHER"
        status_code = int(status_code) if 100 <= int(status_code) <= 599 else 500
        if not math.isfinite(duration_ms):
            return
        key = f"http_request_ms|{method}|{normalize_operation(operation)}|{status_code}"
        with self._lock:
            self._durations[key].append(max(0.0, float(duration_ms)))
            self._counters[f"http_requests|{method.upper()}|{normalize_operation(operation)}|{int(status_code)}"] += 1

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            durations = {
                key: {
                    "count": len(values),
                    "mean_ms": round(sum(values) / len(values), 3) if values else 0.0,
                    "max_ms": round(max(values), 3) if values else 0.0,
                }
                for key, values in self._durations.items()
            }
            return {"schema_version": "repolens.metrics.v1", "counters": dict(self._counters),
                    "durations": durations}

    def prometheus(self) -> str:
        snapshot = self.snapshot()
        lines = ["# HELP repolens_http_requests_total HTTP requests handled by RepoLens.",
                 "# TYPE repolens_http_requests_total counter"]
        for key, value in sorted(snapshot["counters"].items()):
            if not key.startswith("http_requests|"):
                continue
            _, method, operation, status = key.split("|", 3)
            lines.append(f'repolens_http_requests_total{{method="{method}",operation="{operation}",status="{status}"}} {value}')
        lines.extend(("# HELP repolens_process_counters_total Internal bounded counters.",
                      "# TYPE repolens_process_counters_total counter"))
        for key, value in sorted(snapshot["counters"].items()):
            if key.startswith("http_requests|"):
                continue
            safe = re.sub(r"[^a-zA-Z0-9_]", "_", key)
            lines.append(f"repolens_process_counters_total{{name=\"{safe}\"}} {value}")
        lines.append("# TYPE repolens_http_duration_sample_mean_ms gauge")
        for key, value in sorted(snapshot["durations"].items()):
            _, method, operation, status = key.split("|", 3)
            lines.append(f'repolens_http_duration_sample_mean_ms{{method="{method}",operation="{operation}",status="{status}"}} {value["mean_ms"]}')
        return "\n".join(lines) + "\n"


def monotonic_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))
