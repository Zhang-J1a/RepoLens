# ADR 0025：可选 LangChain 模型链与 Retriever 适配

状态：已采纳。适用于 V6 之后的可选集成，不改变核心依赖和 V1-V6 已冻结的产品边界。

## 背景

LangChain 在 GitHub 项目中常用于统一 Prompt、模型调用、结构化输出和 Retriever 接口。RepoLens 已有本地 SQLite 检索、snapshot/evidence provenance、上下文预算、citation validator，以及有明确工具与预算边界的 Agent。整体替换会增加核心安装体积，并将稳定的数据/权限边界耦合到快速变化的 orchestration API；继续完全不用 LangChain 又无法验证其常见集成方式。

## 决策

1. 提供 `langchain` 可选 extra，依赖实际使用的 LangChain Core、`langchain-deepseek`，并显式声明用于关闭 tracing 的 LangSmith 依赖；不拉入未使用的 LangGraph Agent 包。未安装 extra 的核心、Web 和 Mock 工作流继续可用。
2. `RepoLensRetriever` 继承 `BaseRetriever`，只访问调用方传入的 RepoLens store 和精确 snapshot，支持现有 keyword/vector/hybrid/graph 策略并把来源字段映射到 `Document.metadata`。
3. `LangChainDeepSeekProvider` 使用 LCEL prompt 与 `ChatDeepSeek.with_structured_output`，仍实现 RepoLens 的 `Provider` 窄接口。模型候选必须经过原有 schema、当前 evidence ID 和 canonical source-span 校验。
4. LangChain 不拥有仓库索引、持久化、snapshot 选择、context budget、query policy 或默认策略；`hybrid` 默认不变。
5. `ControlledAgent` 保持 RepoLens 的固定只读工具、显式状态机、进程隔离和共享预算。LangChain integration 不启用任意 `create_agent`/tool execution，也不授权模型自行调用 shell、文件或网络工具。
6. 适配器用 `tracing_context(enabled=False)` 显式关闭 LangSmith tracing，即使全局 tracing 环境变量为 true，也不上传 Retriever/Prompt/模型数据。可选依赖和测试不得要求 API Key；CI 仅运行离线 adapter 测试，不发起真实 provider 请求。
7. 原 V6 冻结清单保持不变；用单独、引用原清单 hash 的策略扩展记录 Retriever/LCEL 实现及 pipeline 接口变更。90 次检索 gold replay 和原始指标不改写。

## 取舍

- 优点：项目展示业界常见的 `BaseRetriever`、prompt template、LCEL 和模型集成能力；DeepSeek 接口不用直接渗透到业务流程；核心用户无需安装 LangChain。
- 成本：LangChain Core、DeepSeek 集成及其传递依赖仍增加体积和升级成本；通过精确 lock 和构造测试防止 API 漂移。
- 边界：LangChain 适配本身不证明检索或回答质量，也不代表使用 LangGraph Agent；真实模型质量仍需固定响应与独立审阅评测。
- 传输边界：适配器在 SDK 接收并解析后检查结构化结果的 4 MiB 上限；它没有复用原生 provider 的 HTTP streaming 字节截断，不能把该检查描述为 SDK 接收前的响应体内存上限。

## 验收

- 锁定可选依赖并在 CI 中安装检查。
- 离线测试 snapshot/evidence provenance、LCEL chain 构造、结构化输出映射、重试上限和敏感错误脱敏。
- 运行完整 Python/Web API/浏览器回归、冻结策略 hash 检查和固定 Flask 90 次检索 replay。
- 不读取真实 API Key，不修改、索引或评测学习参考仓库。
