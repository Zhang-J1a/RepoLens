"""Bounded process-local task results and resumable SSE event history."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import copy
import logging
import threading
import time
import uuid

from repolens.domain import RepoLensError
from repolens.observability import bind_request_id, request_id, reset_request_id


LOGGER = logging.getLogger("repolens.tasks")


class JobStore:
    def __init__(self, service, capacity=24, metrics=None):
        self.service = service
        self.capacity = capacity
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="repolens-workbench")
        self.jobs = {}
        self.metrics = metrics

    def submit(self, payload):
        with self.lock:
            if len(self.jobs) >= self.capacity:
                finished = next((key for key, value in self.jobs.items()
                                 if value["status"] in ("completed", "failed")), None)
                if finished is None:
                    raise RepoLensError("任务队列已满，请等待当前任务完成。")
                del self.jobs[finished]
                if self.metrics:
                    self.metrics.increment("tasks_evicted")
            identity = uuid.uuid4().hex
            self.jobs[identity] = {
                "id": identity, "action": payload["action"], "workspace_id": payload.get("workspace_id"),
                "status": "queued", "created_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": 0, "events": [], "error": None, "result": None,
                "request_id": request_id(), "error_code": None,
            }
            self.emit(identity, {"state": "queue", "status": "queued"})
            self.pool.submit(self._run, identity, payload, request_id())
            if self.metrics:
                self.metrics.increment("tasks_submitted")
            return self.get(identity)

    def emit(self, identity, event):
        with self.lock:
            job = self.jobs[identity]
            # V3 is bounded to 32 steps; this additionally caps UI event retention.
            if len(job["events"]) < 512:
                job["events"].append({"id": len(job["events"]) + 1,
                                      "timestamp": datetime.now(timezone.utc).isoformat(), "data": copy.deepcopy(event)})

    def _run(self, identity, payload, parent_request_id):
        token = bind_request_id(parent_request_id)
        started = time.monotonic()
        with self.lock:
            self.jobs[identity]["status"] = "running"
        self.emit(identity, {"state": "analysis", "status": "started"})
        try:
            result = self.service.execute(payload, lambda event: self.emit(identity, event))
            with self.lock:
                self.jobs[identity]["result"] = result
                self.jobs[identity]["status"] = "completed"
        except Exception as exc:
            message = str(exc) if isinstance(exc, RepoLensError) else "本地操作失败，请检查仓库、索引权限或重新导入。"
            with self.lock:
                self.jobs[identity]["error"] = message
                self.jobs[identity]["status"] = "failed"
                self.jobs[identity]["error_code"] = "invalid_operation" if isinstance(exc, RepoLensError) else "local_failure"
        finally:
            with self.lock:
                job = self.jobs[identity]
                job["duration_ms"] = round((time.monotonic() - started) * 1000)
                self.emit(identity, {"state": "task", "status": job["status"], "error": job["error"]})
                if self.metrics:
                    self.metrics.increment("tasks_" + job["status"])
                    if (job["result"] or {}).get("status") == "degraded":
                        self.metrics.increment("tasks_degraded")
                result = job["result"] or {}
                trace = result.get("trace_id") or result.get("telemetry", {}).get("trace_id")
                LOGGER.info("task complete", extra={"operation": payload["action"], "task_id": identity,
                                                     "trace_id": trace,
                                                     "duration_ms": job["duration_ms"], "error_code": job["error_code"]})
            reset_request_id(token)

    def get(self, identity, *, result=True):
        with self.lock:
            if identity not in self.jobs:
                raise KeyError(identity)
            job = self.jobs[identity]
            return copy.deepcopy(job if result else job | {"result": None})

    def listing(self):
        with self.lock:
            return [self.get(key, result=False) for key in reversed(self.jobs)]

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)
