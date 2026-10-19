# ADR 0009：V2 生成链路的边界与安全 telemetry

## 状态

已接受，适用于 V2.2.0。

## 背景

V2 已经能够完成检索、上下文打包、provider 调用和 citation 校验。作为可复用的个人项目，还需要防止命令行参数、模型输出和远端响应造成无界资源消耗，同时要能定位一次请求，但不能把源码、prompt 或密钥写进结果和日志。

## 决策

1. CLI 对检索条数、上下文预算、输出预算、超时和重试次数做 typed range validation；非法值在打开索引前以 exit code 2 结束。
2. `ProviderRequest` 将输出 token、context 字节数和 evidence ID 约束在有限范围内；回答 validator 对 claims、citations、unknowns 及文本长度设置上限。
3. DeepSeek provider 将响应体限制为 4 MiB，只对有限的临时错误重试；认证错误不重试，错误信息不携带服务端原文或 API key。
4. 每次 answer 生成本地 `trace_id`，并在结果中返回 provider、model、usage、request id、attempts 和耗时；不返回 prompt、完整模型原文或源码 excerpt。
5. telemetry 是结果元数据，不替代固定数据集上的生成质量、引用精度、拒答和延迟评测。

## 后果

- CLI 和 provider 的资源边界可测试、可解释，模型异常输出不会无限扩大结果。
- 真实调用失败时有足够的 request-level 诊断信息，同时保持密钥和代码内容不进入错误/日志边界。
- 输出增加了 `telemetry` 顶层字段，但既有 `answer` schema 和 canonical citation 结构保持兼容。
