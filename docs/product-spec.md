# 产品规格

## 1. 产品定义

**RepoLens / ChangeGraph-RAG** 帮助开发者理解 Git 仓库并分析代码变化。它检索源码、符号、测试、文档、配置和 Git 历史，输出带可检查证据的结构化报告。

产品目标是**仓库无关**：用户选择自己拥有或获授权读取的仓库。`D:\RAG\all-in-rag` 和 `D:\RAG\AgentGuide` 只是个人学习参考，不是产品输入、依赖或默认评测集。Flask 只是第一个固定真实评测对象。

## 2. 用户场景

- 新加入项目的开发者需要定位模块并理解执行路径。
- Review 者需要识别 diff 影响的调用方、测试、配置和文档。
- 维护者需要区分仓库明确记录的设计理由与推测。
- 仓库所有者需要看到结论的证据、版本和不确定性。

## 3. 初始任务类型

1. **Repository question**：针对选定 snapshot 回答代码问题。
2. **Commit impact analysis**：分析某个完整 commit 影响的文件、符号、测试、文档和配置。
3. **Diff risk review**：基于可解析 diff 识别候选风险，并说明证据与不确定性。
4. **Historical investigation**：检索历史 commit、message 和记录过的设计理由。

路线图 V1 已覆盖确定性 lexical retrieval、可替换 `EmbeddingProvider`、本地 TF-IDF vector baseline、vector/hybrid retrieval、evidence 评测和基于父 snapshot 的 blob 级增量索引。包版本 4.1.0 仍保留此前交付的 provider、DeepSeek、`ask/chat`、基础 impact 和本地 Web UI，但这些能力不改变路线图中 V2-V6 的职责划分。

## 4. 任务契约

| 任务 | 输入 | 必须输出 | 失败行为 |
|---|---|---|---|
| Repository question | 选定仓库 snapshot 和自然语言问题 | 回答、证据定位和 unknowns | 没有证据时 abstain；不支持时明确说明覆盖边界 |
| Commit impact analysis | 仓库和完整 commit SHA | 影响文件/符号/测试/文档/配置、证据、风险和建议测试 | commit 不可用时拒绝；解析不完整时报告 partial |
| Diff risk review | base snapshot 和可解析 diff | 候选风险、影响面、证据、建议测试和不确定性 | 空或非法 diff 时拒绝 |
| Historical investigation | 历史、可选 as-of commit 和问题 | 相关历史证据，区分记录事实与推断 | 缺少历史/理由时明确说无法确定 |

所有任务最终使用统一的结构化 report envelope。任何 material claim 必须绑定 evidence，或明确标为 inference；证据不能指向不存在的文件、symbol、行或 commit。

## 5. 当前输入边界

V1 接受本地 Git working tree 或 bare repository，以及本地已存在的 commit/ref（默认 `HEAD`）。只读取 committed Git blobs，不包含 dirty/untracked 内容；查询要求精确 snapshot ID。索引不会检出文件、运行仓库代码、安装仓库依赖或联网获取对象。

当前 parser 先支持 Python AST 和有限 Markdown heading；向量层的本地 TF-IDF 只作为离线 baseline，不等价于通用语义 embedding。这些实现顺序不限制产品未来的仓库身份。额外语言和外部 provider 必须通过独立 adapter 与语言/服务级 fixture 验证。

## 6. 报告契约（目标）

- `summary`：简洁结论。
- `changed_files`：base/head 之间的文件状态、hunks、分类和变化 symbol。
- `related_tests` / `related_docs`：来自 head snapshot 的可校验证据。
- `risks`：严重级别、理由、evidence_ids 和 `inference` 标记。
- `suggested_tests`：由变化和证据支持的测试建议。
- `evidence`：类型、相对路径、symbol、行范围和 commit SHA。
- `unknowns`：缺失证据、未回答问题和不确定性。
- `trace_id`：回答、工具和规则报告关联的审计 Trace ID；Agent 同时返回 task ID。

当前实现已经提供稳定 evidence 记录、line-span 校验、关键词/向量/混合检索、snapshot 绑定的 bounded Git history、结构化回答、canonical citation validation、无证据 abstention、有界追加检索和 `repolens.impact.v2` JSON/Markdown 报告。impact 目前支持本地 commit、Python symbol 解析、Python AST 的有限直接 callers/callees、Markdown/测试/配置/历史词法关联和四级规则风险。V3 增加八个固定工具、显式状态机、共享预算、工作进程超时回收、task/trace ID 和模型失败降级；V5 已提供六页面工作台。复杂设计理由抽取、动态/跨语言调用图和跨语言 parser 仍未完成。

## 7. 风险政策

V4 额外提供 snapshot-scoped SQLite 图、增量语法事实与重新连边、函数/文件/commit 的两跳子图和版本检索 API。图增强和检查排序可以显式选择，删除文件的旧关系单独显示在 base 子图中；这些能力不等同于动态执行图或 V5 工作台。

风险标签必须是规则支持的摘要，而不是没有依据的模型置信度。每个风险都要写出可观察条件、影响面、证据和缺失证据。V2 将在模型介入前先定义并测试确定性的初始 rubric；当前 Mock provider 只验证回答契约，不作为风险判断或答案质量证据。

## 8. 非目标

- 第一版不做通用 PDF/文档问答。
- 不自动修改代码、应用 patch 或部署。
- 不做无边界的代码生成聊天机器人。
- 不在首版支持所有语言。
- 不要求 hosted vector DB、graph DB、Redis 或 Kubernetes。
- 不把模型输出当成事实来源。
- 不把个人学习仓库变成产品必需输入。

## 9. 成功标准

V0 验证产品契约和可重建 fixture。V1 必须在固定真实仓库、固定 commit 和人工证据集上报告检索指标，并保持稳定的文件/symbol/行引用。V2 验证结构化影响报告、引用、风险分级和证据不足处理。V3 验证固定只读工具、task/trace ID、失败降级、预算/超时和可复现实验。V4 验证持久化静态关系、增量更新、函数/commit 的一至两跳子图、历史版本隔离、节点/边可追溯，以及图增强相对纯向量在固定跨文件任务上的真实收益；同时报告通用问题回退，默认检索不因局部收益自动替换。V5 验证工作区、变更、图、问答、Trace 和评测页面的端到端流程。V6 验证冻结评测回归、结构化日志/metrics、安全边界、容器构建、CI 和部署回滚文档。生成质量、citation precision、abstention precision/recall、impact 风险召回和真实负载延迟必须分别评测，不能由 UI 或 schema 通过推断。

## 10. 后续决策问题

V5 完整工作台提供仓库、变更分析、关系图、检索问答、Trace 和评测页面。代码/diff 从指定 snapshot 读取，报告可导出；任务有 SSE 阶段进度、失败状态和受控 Agent 事件。V6 增加可重复回归、安全说明、结构化日志、metrics、容器和部署文档。使用见 `docs/v5-workbench.md`、`docs/deployment.md` 和 `docs/threat-model.md`。动态关系和跨语言 parser 仍是后续范围。

- 本地 TF-IDF 与 FTS5 混合是否在冻结验证集上有足够可测收益；外部 embedding 是否值得引入源码外发风险？
- 继续支持哪一种语言，应该由 benchmark 价值而不是流行度决定。
- 私有仓库的 trace/source snippet 需要什么保留、脱敏和访问控制策略？
