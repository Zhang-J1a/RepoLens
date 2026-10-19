# ADR 0008：DeepSeek provider 使用标准库 HTTPS 适配

## 状态

已接受，适用于 V2.4 及 V2.2.0 的 provider hardening。

## 背景

RepoLens 已有 vendor-neutral `Provider` 接口、上下文预算和 citation 校验。需要接入真实模型，但不能让 API SDK、密钥或网络失败污染检索和离线测试边界。

## 决策

1. 首个真实 provider 使用 DeepSeek Chat Completions 的 OpenAI-compatible HTTP 接口，默认 base URL 为 `https://api.deepseek.com`，请求路径为 `/chat/completions`。
2. 使用 Python 标准库 `urllib.request`，不新增运行时依赖；`MockProvider` 继续作为默认 provider 和离线测试路径。
3. API key 只读取 `DEEPSEEK_API_KEY` 环境变量；不提供 `--api-key` 参数，不把 key 写入 prompt、错误、日志或结果文件。
4. 默认模型为 `deepseek-v4-flash`，可用 `DEEPSEEK_MODEL` 或 `--model` 覆盖。
5. 使用 JSON mode 请求结构化候选；返回内容仍必须通过 RepoLens 的 schema 和 citation validator，不能信任模型自报的路径、行号或 evidence ID。
6. 只对有限的临时 HTTP/网络错误重试；401 等认证错误不重试。超时、重试次数和模型可通过环境变量或 CLI 覆盖。
7. provider 对响应体设置 4 MiB 上限；返回 provider request id、usage、attempts 和耗时等安全元数据，但不返回完整响应错误体、prompt 或密钥。

## 后果

- 运行依赖保持为零，离线测试可通过注入 opener 完成，不需要联网或真实 key。
- provider 与检索、上下文和 citation 校验保持解耦。
- 真实模型质量、API 可用性和 token 计费仍需要单独记录和评测；provider 接入本身不代表回答正确。
- 真实 smoke test 只能证明端到端连通和契约通过；完整回答质量仍需固定问题集和独立指标。
