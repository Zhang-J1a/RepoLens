# 面试讲解与演示

## 一分钟介绍

RepoLens 是我面向通用 Git 代码仓库实现的证据优先本地 RAG 与变更影响分析系统。它从指定 commit 读取源码，通过 Python AST 和 Markdown 分块建立 SQLite/FTS5 索引，检索结果带可验证的文件、symbol、行号和版本。V1 完成离线索引、检索、证据查验和评测；V2 完成 provider 接口、上下文预算、结构化回答、citation 校验、无证据 abstention、DeepSeek 和 impact 报告；V3 增加受控 Agent、工具白名单、预算和 Trace；V4 增加持久化代码图和版本感知检索；V5 增加六页面 Web 工作台；V6 增加回归门禁、结构化日志、metrics、安全模型、Docker 和部署回滚文档。真实 smoke test 已通过，但不冒充完整生成质量评测。

重点不是服务数量，而是三个可验证问题：历史查询不会混入工作区未提交内容，返回的引用确实对应固定版本的源码，检索改动有冻结数据和逐题结果支持。

后续按明确需求增加了可选 LangChain Core 的 LCEL、`BaseRetriever/Document` 和 DeepSeek ChatModel 集成。版本、索引、引用验证和 Agent 权限由 RepoLens 保留；可以讲清框架解决了什么问题，以及为何没有把受控 Agent 改成任意工具执行。该次接入通过本地离线验收，真实模型质量尚未评测。

2026-10-20 优化补充：README 已与实际跨平台/容器 CI 全绿证据同步；M4 多仓库选仓按作者要求暂缓。新增 Mock 离线评测断点执行器及只读 MCP stdio 最小服务；真实模型评测、完整 MCP 客户端生态兼容与跨仓库质量仍未验收。当前优先演示工作台、失败边界与冻结评测，MCP 接入方式见[独立文档](mcp.md)。

## 五分钟演示

1. 运行 `repolens doctor`，展示运行依赖与不需要 API key 的本地能力。
2. 运行 `python scripts/demo.py`，展示合成 Taskboard 的索引、检索、evidence 和工作树不变检查。
3. 指定一个授权仓库与 commit，用 `ingest` 获得 snapshot，再用同一 snapshot 搜索和查证据。
4. 打开 `eval/flask-v1-validation.json`，展示总体分数和分类差异；说明纯中文检索失败是词法系统的已知边界。
5. 运行 `repolens answer ... --provider mock --context-tokens 1200`，展示 `E1` citation 如何回填到 snapshot、commit、path、symbol 和行号；再用无命中问题展示 provider 调用前 abstain。
6. 在本机环境变量中设置 `DEEPSEEK_API_KEY` 后，用同一个问题运行 `--provider deepseek`，保留请求配置、输出和错误边界，不把 key 写进项目。
7. 打开 `docs/evaluation-review-v1.3.md`，解释未采用的标识符子查询融合负实验；区分它与当前 keyword/vector hybrid 使用的 RRF。
8. 用两个本地 commit 运行 `impact --provider mock`，展示变更文件、Python symbol、相关测试/文档 evidence、规则风险和 `inference` 标记；再说明 `--provider deepseek` 只增加一次模型摘要。
9. 打开 V5 六页面工作台，展示仓库、变更、关系图、问答、Trace 和评测；说明页面复用现有 pipeline，不创造新的事实来源。
10. 运行 `python scripts/v6_regression.py`，展示冻结评测 hash 门禁；再查看 `/api/metrics`、结构化日志、威胁模型和 Docker Compose，说明当前部署边界仍是本地单用户。

## 可以深入讲的取舍

| 问题 | 实现与取舍 |
|---|---|
| 为什么读取 Git objects？ | 直接绑定 commit，不依赖工作树状态，也不运行目标代码和 checkout filters |
| 为什么先用 SQLite？ | 事务、可重建、无外部数据库服务；FTS5 提供明确的词法基线 |
| AST 比固定字符切分有什么价值？ | 可记录函数/方法边界、qualified name 与行号；长函数仍切成有上限的重叠 chunks |
| 什么保证引用可查？ | ID 包含 snapshot/blob/路径/范围；结果返回前逐行核对存储源码 |
| 为什么重排前固定候选数？ | 用户只改返回条数时应得到同一个排名的前缀；候选池变化会破坏这个契约 |
| 同名符号怎么处理？ | getter/setter、overload 都可能同名；定位时结合包含行范围，不拿 SQL 第一条当唯一符号 |
| 如何防止只看平均分？ | 记录逐题与按类别指标，区分零命中、部分证据遗漏、排序回退和标注不足 |
| 为什么保留融合负结果？ | 早期标识符子查询融合使开发集 R@10 从 0.792 降到 0.753，未采用；当前 hybrid 的 keyword/vector RRF 是另一项独立评测的策略 |
| 追加检索如何避免变成失控 Agent？ | 每轮最多一次 provider 调用，最多追加 3 次；query 只来自当前问题、历史 user terms、已检索 symbol/path，达到 answered 立即停止 |
| impact 如何保证版本一致？ | base/head 各自建立精确 snapshot；变更文件用本地 commit diff，删除文件引用 base evidence，当前文件和相关测试/文档引用 head evidence |
| impact 的风险是不是模型拍脑袋？ | 初始风险来自固定规则并标记 `inference`；模型摘要仍必须引用 evidence，不能覆盖规则事实 |
| 为什么还要新验证集？ | 原 30 题参与过调参；新增题在运行前冻结，不再用其结果调整权重 |
| 为什么做本地 Web UI 而不是只做 CLI？ | CLI 保留可复现和 CI 能力；Web UI 降低使用门槛，仍绑定 loopback，不引入远程服务或新的事实来源 |
| 上下文过长怎么处理？ | evidence 作为不可拆分单元按固定预算贪心装箱；超过预算的证据被记录并淘汰，不截断源码，不把超预算内容交给 provider |
| 如何防止模型胡乱引用？ | 模型只能返回本次 pack 产生的 `E1` 等短 ID，RepoLens 从已校验 evidence 回填 canonical locator；未知 ID 或无引用 claim fail closed |
| 没有证据时怎么办？ | 检索为空或预算容纳不了任何 evidence 时，在 provider 调用前直接返回 abstained |
| 如何定位一次请求？ | 每次 answer 生成本地 trace id；真实 provider 返回的 request id、usage、attempts 和耗时只作为安全 telemetry 返回，不记录 prompt、源码或密钥 |
| LangChain 具体用在哪里？ | LCEL prompt/model chain、DeepSeek 结构化输出和 BaseRetriever/Document 适配；保留本地索引、上下文预算和 canonical citation validator |
| 为什么没有使用 LangGraph Agent？ | 当前 ControlledAgent 已有固定工具、任务预算、spawn 超时和版本边界；可选模型适配器复用这些约束，不因为接入框架扩大权限 |
| 框架接入有什么验收证据？ | 184 项 Python、11 项最终安装包专项、8 项浏览器和实际 LangChain Retriever 的 90 次冻结重放；模型质量仍单独标记未测 |

## 数据应怎样表述

可以说：V4 固定 Flask 的 10 题跨文件任务 R@10 从 vector 0.80 提高到 graph 0.95；原有 20 题则是 hybrid 0.6083、graph 0.50，因此保留 hybrid 默认。V6 重放两套题、三种策略的 90 次查询，逐题与冻结记录一致。当前 Python、浏览器、安装包和部署验证状态见 [V6 交付记录](v6-release.md)。V1 历史 keyword 开发集 0.792、验证集 0.650 属于早期策略，不能替代当前三路评测，也不能把这些检索数字称为回答准确率。

不能将这些数字改称“回答准确率”“任意仓库准确率”或“生产性能”。这不是多仓库外部盲评；Mock provider 只证明 schema/citation/abstention 契约，还没有真实模型的引用 precision、回答正确率和真实负载吞吐量。

## 简历描述示例

开发本地 Git 代码 RAG 与变更分析工作台 RepoLens：基于 commit objects、Python AST 和 SQLite 实现版本隔离、混合/图检索和可查证引用；通过 LangChain Core LCEL 与自定义 Retriever 接入 DeepSeek，保留引用校验和受控 Agent 预算，提供冻结评测、Web 工作台与独立安装包。

如果写数字，附上数据集规模和条件，不把开发集分数当成通用效果。DeepSeek provider 的接入本身不等于回答质量已验证；还要单独评估回答正确率、citation precision、abstention precision/recall 和延迟。
