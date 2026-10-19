# ADR 0007：V2 采用证据优先的结构化生成边界

## 状态

已接受，适用于 V2.1-V2.3。

## 背景

V1 已能在固定 snapshot 内返回经过 source-span 校验的 evidence，但还没有生成回答。直接把检索文本拼进 prompt 会产生三个工程风险：上下文可能无界增长，模型可能引用未提供的文件或行号，检索为空时系统仍可能生成看似合理的内容。

## 决策

1. provider 只实现窄的 `ProviderRequest -> ProviderResponse` 接口，不让 SQLite、Git 或某家模型 SDK 渗透到检索层。
2. `EvidenceContextPacker` 按确定性 token 估算和固定预算装入完整 evidence；不截断单条 evidence，去重并记录被预算淘汰的 evidence。
3. 上下文中的 evidence 使用本次请求的短 citation ID，例如 `E1`。模型只能返回这些 ID，RepoLens 再把 ID 映射到已校验的 evidence、snapshot、commit、路径、symbol 和行号。
4. provider 输出必须满足 `repolens.answer.v1`：`answered` 的每个 claim 至少有一个合法 citation；`abstained` 不得包含 claim 或 citation，并必须说明 unknowns。
5. 检索为空或上下文预算无法容纳任何 evidence 时，在 provider 调用前直接 abstain。非法 schema 或未知 citation fail closed，不静默改写成事实。
6. 先提供不联网的 `MockProvider`，待契约和离线测试稳定后再接 DeepSeek 等真实 provider。

## 后果

- 无证据生成和“引用看起来像真的”这两类错误在边界处被阻断。
- citation 的稳定性来自已有 evidence 校验，而不是模型自报的文件和行号。
- token 估算是规划预算，不是服务商实际 tokenizer 或计费量；接入真实 provider 时仍需记录服务商 usage。
- Mock provider 只能证明编排和 schema 行为，不能证明回答正确性；真实模型接入后必须新增生成质量、citation precision 和 abstention 评测。
