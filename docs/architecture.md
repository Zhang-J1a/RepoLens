# 架构说明

## 1. 设计约束

- evidence 和 repository snapshot 是事实来源，生成文本不是事实来源。
- 核心索引、检索与离线测试保持本地、可重建；SQLite 是持久化边界，外部模型和 Web 依赖保持可选。
- 解析器和未来模型 provider 通过窄接口隔离，避免把某个仓库或服务商写死在产品里。
- 每次只分析选定的仓库版本，检索和证据必须防止未来版本泄漏到历史 snapshot。
- 仓库文本是非可信输入；注释、文档和 fixture 不能改变工具权限或系统规则。
- 先验证确定性索引、检索和证据，再考虑 Agent 和 UI。

## 2. 逻辑流程

~~~text
用户选择的本地 Git 仓库
  -> 仓库校验与 commit/snapshot 选择
  -> Git 元数据与 tree inventory
  -> 语言/文档解析器
  -> 带 provenance 的标准化 artifact、symbol、chunk
  -> SQLite 记录与 FTS5 索引
  -> snapshot 过滤后的 keyword / vector / hybrid retrieval
  -> evidence 扩展、范围校验与离线评测
  -> V2 context budget、provider、结构化回答与引用验证
  -> V3 bounded follow-up retrieval / chat
  -> V2 commit impact：base/head snapshot、diff、symbol、测试/文档 evidence、规则报告
  -> V3 controlled agent tools and trace
  -> V4 code graph and history-aware retrieval
  -> V5 local Web UI / loopback API / double-click launcher
  -> V6 engineering, evaluation, and deployment
~~~

V1.1 实现了仓库校验、commit object inventory、Python/Markdown 解析、稳定证据 ID、SQLite/FTS5、snapshot 过滤和 evidence span 校验。V1.2 增加 JSONL 评测器及 `evaluate` CLI，计算 Recall@5/10、MRR、nDCG@10、类别宏平均与延迟。V1.3 增加 FTS5 候选池、代码标识符覆盖率和 symbol 层级重排；当前 V1 对齐增加可替换 embedding 契约、本地 TF-IDF、vector/hybrid 检索和父 snapshot 的 blob 级增量索引。此前已经实现的 provider、DeepSeek、`ask/chat`、基础 impact 和 Web UI 保留，但后续按路线图分别归入 V2、V3 和 V5。

## 3. 模块职责

Python 包版本为 4.1.0，路线图阶段为 V6；两者编号独立，V6 是否完成以 `docs/v6-release.md` 的验收边界为准。

| 模块 | 职责 | 状态 |
|---|---|---|
| `config` | 数据目录选择与目标路径保护 | V1.1 |
| `domain` | commit、tree、parsed file、symbol、chunk 与稳定 ID | V1.1 |
| `git` | 本地 commit 解析、bounded history、tree inventory、Git blob 读取、bounded diff/hunk 读取 | V1.5/V3.3 |
| `ingestion` | 组装 snapshot 并事务写入 SQLite | V1.1 |
| `parsing` | Python AST 与 Markdown ATX section 解析 | V1.1 |
| `index` | SQLite schema、history/FTS5/BM25、snapshot 过滤、vector model/chunk vectors 和 evidence 展开 | V1.1/V1.4/V1.5 |
| `evaluation` | 数据集/证据校验、检索指标、延迟与运行元数据 | V1.2 |
| `retrieval` | FTS 候选重排、查询标识符特征和有限中文代码词扩展 | V1.3/V4.1 |
| `embeddings` | 可替换 EmbeddingProvider、本地 TF-IDF 稀疏向量和 cosine 相似度 | V1.4 |
| `cli` | `ingest/search/history/evidence/snapshots/evaluate/answer/ask/chat/impact/serve` 命令入口、参数边界及有界 ask/chat 工作流 | V1.5/V5 |
| `diagnostics` | `doctor` 环境诊断，无需创建索引 | V1 完整交付 |
| `context` | 完整 evidence 打包、token 预算、去重和淘汰记录 | V2.2 |
| `provider` | vendor-neutral 请求/响应契约、离线 Mock、DeepSeek provider、重试和响应保护 | V2.1/V2.4/V2.2 |
| `langchain_integration` | 可选 LangChain `BaseRetriever`、LCEL prompt/model chain 与 DeepSeek 结构化输出适配；保留 RepoLens 验证边界 | V6 可选适配 |
| `answer` | 严格回答 schema、citation 映射、canonical evidence 校验和 fail-closed 处理 | V2.4 |
| `pipeline` | 检索、上下文预算、provider、回答验证与安全 telemetry 编排 | V2.1-V2.2 |
| `impact` | base/head snapshot 比较、变化 symbol、有限 Python callers/callees、测试/文档/配置/历史 evidence、四级规则风险、JSON/Markdown 报告和一次性模型摘要 | V2.1/V3.3 |
| `impact_rendering` | 纯 Markdown 展示，复用结构化 impact 报告，不读取 Git/索引或调用模型；原 `impact.render_impact_markdown` 导入兼容 | M9 |
| `webapp` | 保留的标准库兼容 UI/API 和共享 WebOperations 层；由 `repolens-ui`/`serve` 入口使用 | 兼容入口 |
| `workbench` / `apps/web` | 当前主工作台：可选 FastAPI/Pydantic、React 六页面、SSE、只读代码/diff、图/Trace/评测与打包启动器 | V5/V6 |
| `graph` | 持久化静态节点/边、增量语法事实、重新连边、一至两跳查询和版本隔离的可选图检索 | V4 |
| `agent` | 八个固定只读工具、显式状态机、共享预算、spawn 超时终止、模型降级和 task/trace 记录 | V3 |
| `observability` | 请求/任务关联、metadata-only JSON 日志、有界 metrics 和 Prometheus 文本端点 | V6 |
| `generation_evaluation` | 为保存回答生成 hash 绑定的独立审阅模板；计算引用支持度、正确率、拒答 F1、unsupported-answer rate 及策略/类别分组 | V6 / M5 准备 |
| `benchmark` | Mock/真实 provider 评测执行、冻结输入、重试预算、断点日志与独立审阅导出 | M5 准备 |
| `mcp_service` / `mcp_server` | 复用受控工具的固定 snapshot 证据服务与 MCP stdio 最小传输 | M7 最小切片 |

表中只列出实际存在的模块。`ask/chat` 的仓库与 snapshot 工作流位于 `cli.py`，问答编排位于 `pipeline.py`；路径、citation、Agent 参数和 Web 请求的验证分别由 `config.py`、`answer.py`、`agent/` 与 `workbench/schemas.py` 承担，不存在独立的 `workflow.py` 或 `validation.py`。

实现保持模块边界小而直接：`git.py` 通过固定命令和 `cat-file --batch` 读取对象；`parsing.py` 使用 `ast` 与有界 Markdown scanner；`index.py` 管理 SQLite schema 和查询语义；`evaluation.py` 只消费已经建立的 snapshot，不执行目标仓库代码。

## 4. 数据与身份

V1.1 至少表示以下实体：

- `Repository`：本地仓库稳定 ID、root 和索引策略。
- `Commit`：完整 SHA、parents、author、时间和 message。
- `HistoryCommit`：snapshot 可达的 bounded 历史提交、父提交、作者、时间和 message；snapshot stats 同时记录包含当前 commit 的本地 branches。
- `Artifact/File`：仓库相对路径、Git blob、内容 hash、版本和状态。
- `Symbol`：qualified name、kind、文件及 1-based 行范围。
- `Chunk/Evidence`：带 snapshot、路径、symbol 和精确行范围的可检索证据。

ID 使用结构化 JSON 组件的 SHA-256。repository ID 包含 canonical local root；snapshot ID 包含 repository、完整 commit SHA 和 parser/index policy；evidence ID 包含 snapshot、路径、blob、kind、symbol 和行范围。解析或 chunk 规则改变时必须改变 policy ID。路径始终是 UTF-8、仓库相对 POSIX 路径，不解析到目标工作树。

## 5. 存储、检索和评测

SQLite 是事务存储。FTS5 对 path、symbol、text 提供可解释的 BM25 检索，当前字段权重为 `path=2.0`、`symbol=6.0`、`text=1.0`；查询输入先拆成字面 Unicode terms，再以 OR 组合，避免用户输入被当作 FTS 操作符。每个 snapshot 同时保存本地 TF-IDF 稀疏模型和 chunk vectors，`search_vector` 使用 cosine 相似度，`search_hybrid` 使用 keyword/vector 的固定权重 RRF 融合。结果按精确 snapshot 过滤。

同一数据库中的多个 snapshot 共享 BM25 corpus statistics，因此可比较实验应使用新建且固定的索引目录。`evaluate` 在跑分前校验数据集只指向一个仓库/commit，且每条 locator 的文件、行范围、可选 symbol 和可检索 chunk 都存在；结果记录 dataset SHA-256、snapshot、index policy、检索参数、索引统计、环境和 P50/P95 延迟。nDCG 对重复 evidence ID 和重复覆盖去重，避免重叠 chunk 虚增分数。

V1 收尾统一所有返回条数的候选预算为 100，避免 `--limit` 改变排名前缀。评测解析同名 symbol 时检查全部定义的包含范围，支持 getter/setter 和 overload。包版本统一从 `repolens.__version__` 获取；独立 `scripts/demo.py` 使用合成临时 Git 仓库验证已安装 wheel。

## 6. 版本与安全模型

- 每个索引 artifact 绑定完整 commit SHA；未提交和未跟踪文件永不进入历史证据。
- 查询必须提供精确 snapshot ID，只能返回该 snapshot 的 evidence。
- Git 读取使用固定命令；关闭 replace refs、lazy fetch、Git hooks 和可选锁，不检出文件、不执行目标代码、不联网。
- 索引目录必须位于目标仓库及其 Git 目录之外。
- 不跟随 symlink 和 submodule；限制单文件、源码总量和 tree 条目，避免无界资源消耗。
- 生成模型若在后续加入，只能把仓库内容当作引用数据，不允许内容改变工具权限或版本边界。V2 的上下文明确标记为不可信仓库数据，provider 返回的 citation 只能引用本次 pack 的短 ID；canonical 文件、symbol、行号和 commit 由 RepoLens 从已校验 evidence 回填。

## 7. 测试策略

- 单测覆盖解析器、稳定 ID、数据库操作、检索过滤、证据范围校验和评测指标。
- 集成测试使用临时 Git 仓库，验证 dirty/untracked 隔离、多 snapshot、bare clone、事务回滚和 CLI。
- Flask 真实评测使用固定 commit 的本地 clone，单独报告，不混入确定性回归测试。
- 评测数据集必须审阅；修改预期证据要记录原因，不能为了分数静默改标签。

## 8. V2 生成边界

问答链路是：`ask/chat` 先根据仓库 root、commit SHA 和 `INDEX_POLICY` 复用或建立精确 snapshot；随后按配置使用 `IndexStore.search`、`search_vector` 或 `search_hybrid`，返回已做 source-span 校验的 evidence。`EvidenceContextPacker` 按确定性估算保留完整 evidence，`Provider` 只能看到打包上下文和 `E1` 等 citation ID，`validate_provider_output` 再把短 ID 映射回 canonical evidence。`chat` 只保留最近 8 条对话消息，并把历史作为上下文，不把历史模型文本当作当前轮证据。追加检索最多 3 次，每次最多一次 provider 调用；成功回答立即停止。检索为空或预算容纳不了任何 evidence 时，在 provider 调用前返回 `abstained`。

`impact` 链路先用本地 Git 比较 base/head，分别复用或创建两个 snapshot；对变更路径读取零上下文 hunks，用 head/base 的索引 symbol 范围关联变化函数、方法和类，再用 head snapshot 的词法检索寻找测试和 Markdown 文档。规则风险只表达可观察条件，并把结论标为 `inference`；模型最多生成一次，且仍使用 `answer.v1` 的 citation validator。rename 目前用 `--no-renames` 按删除和新增处理。base/head evidence 保留各自 snapshot ID，避免把旧代码引用误标成当前代码。

V5 `webapp` 只绑定 loopback 地址，浏览器页面通过 `/api/ask` 和 `/api/impact` 调用既有 pipeline，不复制检索或回答逻辑。仓库路径和 index path 只保存在浏览器本地以改善再次使用体验；API Key 只保存在服务进程内存，设置接口不返回密钥，服务停止即失效。`.pyw` 启动器通过 `pythonw` 启动服务并自动打开浏览器；CLI 和 HTTP API 共用相同的边界校验。

现有 multilingual expansion layer 在 FTS5 查询表达式之前扫描有限的中文代码问题词典，生成 `main`、`read`、`save`、`book` 等英文/代码提示，并保留用户写出的 identifier；原始问题仍作为 query 输入的一部分，扩展词数量和总 term 数受原有上限约束。该层不调用模型、不读取仓库外部数据、不声称通用翻译能力。

当前 token 预算是规划估算，不是任何具体服务商的计费 token；单条 evidence 不会被截断。模型返回未知 citation、没有 citation 的事实 claim、非法字段、超量 claims/unknowns 或不满足 answered/abstained 约束时 fail closed。`MockProvider` 只用于离线契约测试，不能代表答案质量。`DeepSeekProvider` 通过标准库 HTTPS 调用 Chat Completions 的 JSON mode，API key 只从环境变量读取；请求超时、可重试的 HTTP/网络错误、响应体大小和重试次数均有界处理，401 等认证错误不重试。输出只携带 provider request id、usage、attempts 和耗时等安全 telemetry，不携带 prompt、源码或密钥。

## 9. 路线图交付边界

V1.2 是未调参 FTS5 基线，V1.3 的 30 题已用于权重选择，应作为开发集结果。当前 V1 对齐增加的 vector/hybrid 和增量索引使用独立 strategy 记录指标，没有覆盖历史 keyword 基线。V1 已有 20 题同仓库验证集，但它仍不是跨仓库盲评。V2-V6 的证据分析、Agent、静态图、工作台及工程化实现见后续章节。动态/跨语言关系与真实生成质量仍待独立验证。所有路径继续不执行目标仓库代码、不修改目标仓库、不联网获取 Git objects，也不提供任意工具调用。

## 10. V3 受控 Agent

`agent/runner.py` 通过 prepare -> baseline -> tool -> agent_plan -> tool/agent_answer -> answer_validation -> stop 显式编排。prepare 固定仓库与 base/head snapshot；所有工具参数仅允许宿主定义的字段，无法传入版本、仓库、shell 或 URL。`tools.py` 注册路线图要求的八个只读工具，使用现有 Git/IndexStore/AST 接口，不执行目标仓库代码。V4 中关系工具升级为持久化图，子图最多两跳；通用搜索保留 hybrid 默认，可显式选择 graph。

`models.py` 定义类型严格的预算和 Trace。`execution.py` 使用 spawn 工作进程执行索引、规则和工具；模型使用单独的有状态工作进程。每次等待使用统一 monotonic deadline 的剩余时间，超时终止并回收进程。工具调用失败消耗步数，累计返回限制不因去重重置；模型规划与最终生成共用请求和 token 预留额度。独立 V2 规则报告仍遵循 V2 自身的文件/证据上限，不计入 Agent 工具返回额度；耗时计入任务总 deadline。

DeepSeek 通过既有 provider 适配层请求 JSON 工具动作，Agent 请求固定 temperature=0。返回动作要通过封闭 schema/工具参数验证，回答继续通过 `answer.v1` citation validator。Mock 使用离线规则规划以复现流程，不能当作真实模型能力评测。commit 范围任务在模型调用前取得 V2 规则报告；模型失败返回 degraded、已取得 evidence 和规则报告，尚未生成的结果不能承诺可用。

Trace 在响应中返回，不默认写盘。所有事件关联 task/trace ID，记录参数、结果定位、合法决策或输出 hash、usage、耗时与分类错误，不记录源码正文和 provider 异常原文。`agent` CLI 与 `/api/agent` 复用同一实现，原有基础问答和 impact 可独立运行。详见 [V3 使用说明](v3-agent.md) 与 [ADR 0021](adr/0021-controlled-agent-budget-and-trace.md)。

## 11. V4 代码图与版本选择

SQLite schema 4 增加图节点、边、构建信息和按路径/blob 缓存的语法事实。新 snapshot 的图与源码同事务保存；增量构建复用未变文件的语法事实，引用始终在新 snapshot 重新解析。图策略 `python-import-scope-graph-v2` 独立于 chunk policy；旧图策略需要重建，旧 evidence ID 不变。

`graph/parsing.py` 仅提取 Python AST 与显式配置 key；`builder.py` 通过模块、导入别名/重导出、词法作用域和单继承解析静态关系。方法裸名称不通过类命名空间查找，遮蔽参数和无法解析的 receiver 不作全局同名猜测。Markdown 完整符号名提及标为 inference。元数据节点使用 Git commit/blob 来源；没有证据时不生成 replaces 断言。

`graph/query.py` 校验 snapshot/commit/path/blob、source span 和符号范围，最多扩展两跳，并用复合外键保证端点同版本。commit 和任意 base/head 范围以实际变化文件作为种子；删除关系放入独立 base 子图，head 不混入旧代码。branch/ref 在 `graph/workflow.py` 中固定成完整 SHA。

图检索使用向量 100 候选加有界语义邻域扩展；节点与边来源一并返回。它在固定 Flask 跨文件 10 题有收益，在原有 20 题有回退，因此保留为可选检索。`impact --with-graph` 增加候选检查优先级，不改变规则风险 rubric。API 提供 `/api/graph` 和 `/api/search`，V5 工作台复用这些接口。详见 [ADR 0022](adr/0022-versioned-static-code-graph.md) 和 [V4 评测](evaluation-graph-v4.md)。

## 12. V5 分析工作台

FastAPI 可选依赖承载封闭 Pydantic 输入、OpenAPI 和生产静态文件；WebOperations 同时供原标准库服务和新服务复用。React/TypeScript 的仓库、变更、图、问答、Trace、评测页面通过 TanStack Query 管理服务端状态，React Router 路由，Monaco 展示只读代码/diff，React Flow/Dagre 展示有界图，Recharts 展示冻结实验。Monaco、语言和 worker 本地打包并按需加载，无 CDN。

单工作线程串行执行最多 24 个保留任务，避免并发索引写入与 Agent observer 交叉；结果、Trace、密钥均仅在进程内。SSE 记录阶段和 Agent metadata-only 事件，支持 Last-Event-ID 补读；前端轮询作为恢复路径。Agent 的 callback 是观察者，异常不会改变分析结果。运行中的索引/问答没有新增强制取消承诺；Agent 的进程预算/超时保持不变。

源码和 diff 接口先验证 snapshot 所属仓库，再读取 IndexStore 的 Git 文本；不读取工作树路径。PR diff 只接受与固定本地 base/head 相符的 diff，不产生新源码事实。评测视图从 V4 冻结结果生成，只读回放 90 条检索逐题检查分数一致，并保存实际召回定位；未修改检索实现或 gold。新视图清单与原始结果 hash 独立保存在 `eval/v5-workbench-view-manifest.json`。

详见 [ADR 0023](adr/0023-v5-web-workbench.md) 和 [V5 使用说明](v5-workbench.md)。V6 实现与尚未验证的部署/模型边界见下一节和 [交付记录](v6-release.md)。

## 13. V6 工程化、安全与部署

V6 增加标准库实现的 request ID、JSON 日志、有限 metrics 和 Prometheus 文本端点；日志只记录路由、状态、耗时、错误类型和 request ID，不记录源码、prompt 或密钥。Web API 增加 CSP、权限策略、跨源限制和拒绝路径的统一 request ID。Agent Trace 继续使用 metadata-only 事件，不默认持久化。

V6 的回归门禁由 `scripts/v6_regression.py` 提供：无索引时校验冻结评测视图、实现策略和来源 hash；提供固定 index 时重放 vector/hybrid/graph 指标并逐题比较。`generation_evaluation.py` 对保存回答和独立审阅标签评分，审阅绑定确切输出 hash；fixture 验证语义评分器，真实 DeepSeek 的 citation precision 和 answer accuracy 保持未测量。

部署使用多阶段 `Dockerfile` 和 `docker-compose.yml`：React 静态资源在构建阶段打包，最终镜像由 FastAPI 同源提供；容器以非 root、只读根文件系统运行，SQLite 使用数据卷，授权仓库只读挂载。V6 不声明多租户、公开部署或任意代码沙箱。详见 [威胁模型](threat-model.md)、[可观测性说明](observability.md)、[部署与回滚](deployment.md) 和 [ADR 0024](adr/0024-v6-engineering-hardening.md)。

## 14. 可选 LangChain 适配

LangChain extra 提供 `RepoLensRetriever` 和 DeepSeek LCEL provider。检索器的构造参数固定 store、snapshot、策略、条数和路径前缀；返回 Document 前校验 snapshot 与 evidence ID/text，随后仍由原上下文打包器处理。模型链只返回结构化候选，最终回答仍由 RepoLens 的 answer schema 和 canonical citation validator 校验。LangChain 不是索引或数据源，也不会改变默认 hybrid 策略。

V3 `ControlledAgent` 保持原有显式状态机、固定只读工具、spawn 超时和共享任务预算；LangChain provider 仅作为兼容模型适配器，不开放 `create_agent` 的任意工具路由。这样采用 LangChain 在 prompt/runnable/retriever 上成熟的接口，同时不把仓库写权限、命令执行或版本选择交给模型。安装和决策依据见 [ADR 0025](adr/0025-optional-langchain-adapter.md)。
