# RepoLens V5 API

FastAPI 实现在 `src/repolens/workbench/api.py`；与 CLI 共用索引、检索、图和 Agent，不复制业务逻辑。

启动：`python -m repolens.workbench.launcher --port 8770 --no-browser`。

接口文档为同源 `/docs`，契约为 `/openapi.json`。输入模型禁止多余字段并严格校验类型。`apps/web/src/api-schema.d.ts` 由此契约生成。

API Key 只接受 `/api/settings` JSON 输入或服务进程环境变量；不通过 URL、任务参数或导出返回。错误响应不回显请求内容。
