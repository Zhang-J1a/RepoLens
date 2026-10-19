"""ASGI request boundary including streaming completion and safe errors."""

import asyncio
import logging
import time
from urllib.parse import urlsplit

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse

from repolens.observability import (
    bind_request_id, monotonic_ms, normalize_operation, reset_request_id, valid_request_id,
)


LOGGER = logging.getLogger("repolens.web")
SECURITY_HEADERS = {
    "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin", "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                               "font-src 'self'; img-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; "
                               "frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
}


class LocalBoundaryMiddleware:
    def __init__(self, app, metrics):
        self.app, self.metrics = app, metrics

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.monotonic()
        headers = Headers(scope=scope)
        identity = valid_request_id(headers.get("x-request-id"))
        token = bind_request_id(identity)
        scope.setdefault("state", {})["request_id"] = identity
        status, sent, completed, error_code, error_type = 500, False, False, None, None

        async def safe_send(message):
            nonlocal status, sent, completed
            if message["type"] == "http.response.start":
                status, sent = message["status"], True
                output = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    output[name] = value
                output["X-Request-ID"] = identity
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                completed = True
            await send(message)

        async def reject(code, text, classification):
            nonlocal error_code
            error_code = classification
            await JSONResponse({"error": text, "error_code": classification, "request_id": identity},
                               status_code=code)(scope, receive, safe_send)

        try:
            host = headers.get("host", "")
            try:
                hostname = urlsplit("//" + host).hostname
            except ValueError:
                hostname = None
            if hostname not in ("127.0.0.1", "localhost", "::1"):
                return await reject(403, "仅接受本机访问。", "host_rejected")
            origin = headers.get("origin")
            if (origin and origin != f'{scope.get("scheme", "http")}://{host}') or headers.get("sec-fetch-site") == "cross-site":
                return await reject(403, "不接受跨站请求。", "origin_rejected")
            app_receive = receive
            if scope["method"] == "POST":
                if headers.get("content-type", "").split(";")[0] != "application/json":
                    return await reject(415, "请求必须为 JSON。", "content_type_rejected")
                content = bytearray()
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect":
                        error_code = "client_disconnected"
                        return
                    content.extend(message.get("body", b""))
                    if len(content) > 128 * 1024:
                        return await reject(413, "请求超过 128 KiB。", "body_too_large")
                    if not message.get("more_body", False):
                        break
                consumed = False

                async def replay_body():
                    nonlocal consumed
                    if not consumed:
                        consumed = True
                        return {"type": "http.request", "body": bytes(content), "more_body": False}
                    return await receive()

                app_receive = replay_body
            await self.app(scope, app_receive, safe_send)
        except asyncio.CancelledError:
            error_code = "request_cancelled"
            raise
        except Exception as exc:
            error_code, error_type = "internal_error", type(exc).__name__
            if not sent:
                await reject(500, "本地操作失败，请检查仓库或索引状态。", "internal_error")
            elif not completed:
                # Finish an interrupted stream without exposing exception text.
                try:
                    await safe_send({"type": "http.response.body", "body": b"", "more_body": False})
                except (OSError, RuntimeError):
                    pass
        finally:
            elapsed = monotonic_ms(started)
            operation = normalize_operation(scope["path"])
            self.metrics.observe_request(scope["method"], operation, status, elapsed)
            LOGGER.info("request complete", extra={"request_id": identity, "operation": operation,
                                                   "status_code": status, "duration_ms": elapsed,
                                                   "error_code": error_code, "error_type": error_type})
            reset_request_id(token)
