"""Typed, loopback-only V5 API and bundled React application."""

import asyncio
from contextlib import asynccontextmanager
import json
import html
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from repolens import __version__
from repolens.config import data_directory
from repolens.domain import RepoLensError
from repolens.impact import render_impact_markdown
from repolens.workbench.jobs import JobStore
from repolens.workbench.schemas import DiffInput, Health, KeyInput, SourceInput, TaskInput, TaskView, Workspace
from repolens.workbench.service import WorkbenchService
from repolens.observability import MetricsRegistry, request_id
from repolens.workbench.middleware import LocalBoundaryMiddleware


def create_app(directory: Path | None = None, *, static_dir: Path | None = None):
    service = WorkbenchService(directory or data_directory())
    metrics = MetricsRegistry()
    jobs = JobStore(service, metrics=metrics)
    static = static_dir or Path(__file__).with_name("static")

    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(jobs.close)

    app = FastAPI(title="RepoLens 分析工作台", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None,
                  description="V6 本地只读 Git 分析。任务和 API Key 仅保存在当前进程。")
    app.state.service, app.state.jobs, app.state.metrics = service, jobs, metrics
    app.add_middleware(LocalBoundaryMiddleware, metrics=metrics)

    @app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
    def api_documentation():
        # Offline documentation remains usable under the same-origin CSP.
        schema = html.escape(json.dumps(app.openapi(), ensure_ascii=False, indent=2))
        return HTMLResponse('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
                            '<meta name="viewport" content="width=device-width, initial-scale=1">'
                            '<title>RepoLens API</title><h1>RepoLens API</h1>'
                            '<p><a href="/openapi.json">OpenAPI JSON</a></p><pre>' + schema + '</pre></html>')

    @app.exception_handler(RepoLensError)
    async def operation_error(request, exc):
        return JSONResponse({"error": str(exc), "request_id": getattr(request.state, "request_id", request_id())}, status_code=400)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # Pydantic input echoes may contain a key or repository content.
        return JSONResponse({"error": "请求字段、类型或范围不符合 API 约定。", "fields":
                             [".".join(map(str, item["loc"])) for item in exc.errors()],
                             "request_id": getattr(request.state, "request_id", request_id())}, status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(request, exc):
        return JSONResponse({"error": "本地操作失败，请检查仓库或索引状态。",
                             "request_id": getattr(request.state, "request_id", request_id())}, status_code=500)

    @app.get("/api/health", response_model=Health)
    def health():
        return {"ok": True, "version": __version__, "key_configured": bool(service.runtime_api_key),
                "data_dir": str(service.default_data_dir)}

    @app.get("/api/metrics", response_model=dict)
    def metrics_json():
        return metrics.snapshot()

    @app.get("/metrics", include_in_schema=False)
    def metrics_prometheus():
        return Response(metrics.prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8")

    @app.post("/api/settings", response_model=dict[str, bool])
    def settings(payload: KeyInput):
        service.runtime_api_key = payload.api_key.strip() or None
        return {"ok": True, "key_configured": bool(service.runtime_api_key)}

    @app.get("/api/workspaces", response_model=list[Workspace])
    def workspaces():
        return service.workspaces()

    @app.get("/api/workspaces/{identity}", response_model=dict)
    def workspace(identity: str):
        return service.details(identity)

    @app.post("/api/demo", response_model=dict)
    def demo():
        metadata = service.demo()
        return {"demo": metadata, "task": jobs.submit({"action": "import", "repository": metadata["repository"],
                                                       "ref": metadata["head"]})}

    @app.post("/api/tasks", response_model=TaskView, status_code=202)
    def start_task(payload: TaskInput):
        # Validate selected workspace and key before queueing expensive operations.
        if payload.action != "import":
            service.workspace(payload.workspace_id)
            if getattr(payload, "provider", "mock") in ("deepseek", "langchain") and not service.runtime_api_key:
                raise RepoLensError("请先在模型设置中提供 DeepSeek API Key。")
            if getattr(payload, "provider", "mock") == "langchain":
                service._provider(payload.model_dump())
        return jobs.submit(payload.model_dump())

    @app.get("/api/tasks", response_model=list[TaskView])
    def list_tasks():
        return jobs.listing()

    def get_job(identity):
        try:
            return jobs.get(identity)
        except KeyError:
            raise HTTPException(404, "任务已过期或服务已重启，请重新发起。") from None

    @app.get("/api/tasks/{identity}", response_model=TaskView)
    def task(identity: str):
        return get_job(identity)

    @app.get("/api/tasks/{identity}/events")
    async def events(identity: str, request: Request, after: int = 0):
        get_job(identity)
        if after < 0 or after > 512:
            raise HTTPException(400, "事件序号超出范围。")
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(400, "事件序号无效。") from None
        if cursor < 0 or cursor > 512:
            raise HTTPException(400, "事件序号超出范围。")

        async def stream():
            nonlocal cursor
            heartbeat = 0
            while not await request.is_disconnected():
                try:
                    current = jobs.get(identity, result=False)
                except KeyError:
                    yield 'event: expired\ndata: {}\n\n'
                    break
                for event in current["events"]:
                    if event["id"] > cursor:
                        cursor = event["id"]
                        yield f'id: {cursor}\nevent: progress\ndata: {json.dumps(event, ensure_ascii=True)}\n\n'
                if current["status"] in ("completed", "failed"):
                    yield f'event: finished\ndata: {json.dumps({"status": current["status"]})}\n\n'
                    break
                heartbeat += 1
                if heartbeat % 40 == 0:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"X-Accel-Buffering": "no"})

    @app.post("/api/source", response_model=dict)
    def source(payload: SourceInput):
        return service.source(payload)

    @app.post("/api/diff", response_model=dict)
    def diff(payload: DiffInput):
        return service.diff(payload)

    @app.get("/api/tasks/{identity}/export")
    def export(identity: str, format: str = "json"):
        result = get_job(identity)["result"]
        if result is None:
            raise HTTPException(409, "任务尚无可导出的结果。")
        if format == "markdown":
            report = result if result.get("schema_version") == "repolens.impact.v2" else result.get("rule_report")
            if report is None:
                raise HTTPException(400, "该任务没有影响分析报告，请导出 JSON。")
            text, extension, media = render_impact_markdown(report), "md", "text/markdown; charset=utf-8"
        elif format == "json":
            text, extension, media = json.dumps(result, ensure_ascii=False, indent=2), "json", "application/json"
        else:
            raise HTTPException(400, "仅支持 json 或 markdown。")
        return Response(text, media_type=media, headers={
            "Content-Disposition": f'attachment; filename="repolens-{identity}.{extension}"'})

    @app.get("/api/evaluations", response_model=list[dict])
    def evaluations():
        path = Path(__file__).with_name("fixtures") / "evaluations.json"
        if not path.is_file():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/") or path.startswith("assets/"):
            raise HTTPException(404, "接口或资源不存在。")
        if not (static / "index.html").is_file():
            return JSONResponse({"error": "前端尚未构建，请运行 apps/web 的 npm run build。"}, status_code=503)
        return FileResponse(static / "index.html")

    return app
