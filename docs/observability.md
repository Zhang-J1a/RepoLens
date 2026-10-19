# RepoLens V6 可观测性

V6 使用标准库实现轻量的本地可观测性，避免为了单机工具引入完整遥测基础设施。

## 请求日志

Web API 为每个请求生成或校验 `X-Request-ID`，响应会返回相同 ID。结构化日志输出 JSON，字段包括 UTC 时间、日志级别、路由、状态码、耗时和 request ID。日志不包含请求 body、prompt、源码、API Key 或模型原始文本；未知错误只返回分类错误和 request ID。

启动工作台时可使用 `REPOLENS_LOG_LEVEL=INFO` 控制应用日志级别。库导入不会自动配置全局 logging handler，只有工作台 launcher 负责配置输出。

## 指标

- `GET /api/metrics`：返回当前进程的 JSON counters 和有限延迟样本。
- `GET /metrics`：返回 Prometheus 风格的本地文本指标。
- HTTP 指标按 method、规范化路由和 status code 聚合；任务 ID 会归一化为 `{id}`，避免高基数。
- 每个有限路由/method/status 组合最多保留 1,024 条延迟样本；未知 URL 合并到 `/other`，未知 method 合并到 `OTHER`。总请求 counter 不受样本窗口截断，mean/max 仅代表最近样本，服务重启后全部清空。
- 任务累计 submitted/completed/failed/degraded/evicted 计数；不接受任意计数名，不以 repository/question 为标签。

这些指标用于本地诊断和演示，不是生产 SLO。V6 尚未接入 OpenTelemetry collector，也不把指标写入外部服务。

## Trace

任务保存提交请求的 request ID，后台线程继承该上下文；完成日志包含 task ID 和问答或 Agent 的 trace ID。轮询和 SSE 请求有自己的 request ID，任务中的 `request_id` 始终指向原提交请求。SSE 请求耗时包含完整连接时间，不是单次工具延迟。

Agent 使用 task ID/trace ID 和 metadata-only event；页面通过 SSE 查看当前任务过程，支持 Last-Event-ID 补读和轮询恢复。Trace 不默认持久化，不包含源码正文、prompt 或未经校验的模型原文。任务因正常预算结束而 degraded 可以仍有可验证回答，因此与 HTTP 500、队列 task failed 分开计数。

## 故障定位

1. 记录页面或 API 返回的 `X-Request-ID`。
2. 查看启动终端中同一 request ID 的 JSON 行。
3. 查询 `/api/metrics` 观察错误状态和耗时变化。
4. 在 Trace 页面查看 Agent 的分类错误、预算消耗和 stop reason。
5. 若索引损坏，停止服务、备份外置 data 目录后删除对应索引并重新 ingest；目标仓库本身不会被修改。
