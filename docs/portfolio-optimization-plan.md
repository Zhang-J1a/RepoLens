# RepoLens 面试作品集优化执行手册

- 文档版本：1
- 日期：2026-10-19
- 状态：可执行计划，不代表已完成
- 目标岗位：AI 应用、RAG、Agent、后端工程实习
- 当前包版本：4.1.0
当前路线图阶段：V6

## 0. 使用方式

本文件供后续 Agent 直接执行 RepoLens 的作品集优化。Agent 读取后，应从“当前状态”开始复核，选择第一个未完成且没有被授权条件阻塞的里程碑，按本文件的执行循环推进。

最终定位：

> RepoLens 是面向人和 coding agent 的只读、版本感知、证据优先代码智能层。它从精确 Git commit 构建可追溯索引，提供混合/图检索、canonical citation、变更影响分析和受控只读 Agent。

本计划不把 RepoLens 扩张成自动修改代码、执行目标仓库或部署变更的 coding agent。除非用户明确改变边界，目标仓库始终是只读输入。

## 1. 强制约束

### 1.1 每次开始前必须完整读取

1. AGENTS.md
2. docs/progress.md
3. 本文件
4. docs/architecture.md
5. docs/development-conventions.md
6. 当前里程碑涉及的 ADR、源码和测试

发生冲突时，以用户当前指令、AGENTS.md 和最新 progress.md 为准，并在交接中记录偏离原因。

### 1.2 未经用户明确授权不得执行

- commit、tag、push、创建远程仓库、发布 release。
- 调用真实付费模型，读取、打印、保存或回显 API Key。
- 下载或 clone 外部仓库。
- 安装新依赖，修改全局 Git 配置或系统设置。
- 修改、索引、运行或评测 all-in-rag、AgentGuide。
- 执行被索引仓库的代码、测试、hooks、构建脚本或依赖安装。
- 修改冻结 gold、历史评测 JSON 或验收日志来制造更好结果。
- 把 fixture、Mock、schema 或 citation 格式通过称为真实回答质量。
- 伪造 V1-V6 Git 历史、回填日期或声称未执行的验收已经通过。

### 1.3 必须暂停并向用户确认

- 选择开源许可证。
- 首次 commit、push、远程 CI、tag 或 release。
- 真实 DeepSeek 调用、允许发送的仓库和费用上限。
- 新增 dense embedding、reranker 或其他第三方运行依赖。
- 选择或获取新的真实评测仓库。
- 允许执行目标仓库测试、修改代码或联网获取 Git objects。
- 删除兼容入口或进行大规模迁移。

### 1.4 Agent 执行循环

每个里程碑都必须执行以下流程：

1. 用只读命令核对 Git 状态、相关实现、测试和已有证据。
2. 在 commentary 中说明范围、不会触碰的边界和关键取舍。
3. 只实现当前里程碑的最小可运行切片。
4. 先运行专项测试，再运行与风险相称的全量回归。
5. 保存确切命令、退出码、用时、结果路径和限制。
6. 更新 docs/progress.md；只有验收条件全部满足才勾选完成项。
7. 检查 git status --short --untracked-files=all，不覆盖用户已有改动。
8. 未获授权时停在可审阅工作树，不 commit、不 push。

## 2. 当前状态：执行前必须重新核对

- main 分支当前没有 commit，所有项目文件均为 untracked。不得伪造历史。
- 约有 42 个 Python 源文件、8,373 行 Python；前端约 5,401 行；17 个测试文件包含 184 个 unittest 测试。
- data/v6-langchain-tests.log 记录 184 项通过，SHA-256 为 c83da3b9ac97aa672f63865209eebedf653bf55a1b67ba52b137ddfad0959659。这是历史本地验收，不代替当前重跑。
- 远程 CI、Docker 实机和真实 DeepSeek 独立质量评测尚未完成。
- 结构化支持 Python 和 Markdown；图关系主要来自 Python AST、import、作用域和有限单继承。
- vector 是本地 TF-IDF 稀疏向量，不是 neural dense embedding。
- 默认检索是 keyword/vector 的 hybrid RRF；graph 保持显式选择。
- 执行前 provider 默认模型是旧别名 `deepseek-v4-flash`；M1 完成后已改为 `deepseek-flash`，变更与单独 policy 扩展记录见 `docs/progress.md`。
- 真实检索证据主要来自一个固定 Flask commit；跨文件图集为 10 题；没有多仓库外部盲测。
- v6-generation-evaluation.json 是 scripted fixture，不是真实模型质量。
- webapp.py 是兼容入口，workbench 和 apps/web 是当前主工作台；暂不直接删除兼容层。

## 3. 可投递作品集的总体验收标准

- [ ] 有真实、可解释的 Git 提交历史，没有伪造或回填。
- [ ] 远程 CI 至少成功运行一次 Windows/Linux Python、前端和容器验收。
- [ ] README 首屏可在 60 秒内说明问题、差异化、架构、指标和运行方式。
- [ ] 默认模型、命令和依赖说明与当前 API 一致。
- [ ] 至少三个未参与调参的真实仓库完成固定 commit 盲测。
- [ ] 真实模型评测报告 answer accuracy、citation precision、claim support、拒答、延迟和成本。
- [ ] 同题比较 full-context、keyword、TF-IDF、hybrid 和 graph。
- [ ] Docker、wheel、CLI、Web、OpenAPI 和浏览器流程有可复现记录。
- [ ] README 主动披露失败案例、产品边界和未验收项。
- [ ] read-only MCP 已实现，或明确列为后续方向而非已完成功能。

## 4. M0：建立当前基线

### 目标

确认工作区、环境、回归、冻结评测和构建状态。不调整检索权重，不修改 gold。

### 步骤

1. 核对 Git。

    git -c safe.directory=D:/RAG/RepoLens status --short --untracked-files=all
    git -c safe.directory=D:/RAG/RepoLens rev-parse HEAD
    git -c safe.directory=D:/RAG/RepoLens check-ignore -v data dist build src/repolens.egg-info

rev-parse HEAD 在首次提交前预期失败。不得修改全局 safe.directory。

2. 核对环境。

    python --version
    git --version
    $env:PYTHONPATH = "src"
    python -m repolens doctor

3. 运行 Python 回归。

    $env:PYTHONPATH = "src"
    python -m unittest discover -s tests -v
    python -m compileall -q src tests experiments scripts

4. 检查前端与契约。依赖缺失时只报告，不自动联网安装。

    npm run format:check --prefix apps/web
    npm run build --prefix apps/web
    python scripts/export_api.py --check

5. data/v4-flask-index 存在时重放冻结评测。

    python scripts/v6_regression.py --index data/v4-flask-index --output eval/portfolio-baseline-retrieval.json

6. 构建验收。

    python scripts/build_release.py --output eval/portfolio-baseline-package.json

7. 在 progress.md 记录运行环境、命令、用时、测试数、退出码、结果 SHA-256 和限制。

### 完成条件

- [ ] 当前 Python 回归有完整日志和退出码。
- [ ] compileall、前端格式/构建和 OpenAPI 结果明确。
- [ ] 冻结评测没有被修改，逐题结果一致。
- [ ] 没有数据库、密钥、下载仓库或虚拟环境进入候选文件。
- [ ] progress.md 已记录本轮事实。

## 5. M1：修复时效性和文档一致性

### 5.1 更新 DeepSeek 默认模型名

搜索：

    rg -n "deepseek-v4-flash|deepseek-flash" . -g "!data/**" -g "!dist/**" -g "!build/**" -g "!eval/*.json"

将运行时默认值改为 deepseek-flash，至少检查：

- src/repolens/provider.py
- docker-compose.yml
- CLI 和 Web 设置默认值
- LangChain adapter
- README、部署和集成说明
- 对应测试

不要修改历史验收 JSON、旧日志或带历史语境的 ADR；必要时注明“当时使用旧别名”。

### 5.2 区分两套版本

所有当前文档统一：

- 包版本是 4.1.0。
- 路线图阶段是 V6。
- 两者不是同一个版本系统。
- 不在本里程碑顺手修改 SemVer。

### 5.3 修正文档模块漂移

对比 docs/architecture.md 与 src/repolens 实际文件，重点检查文档提到但不存在的 workflow、validation 等模块：

- 职责在其他模块时，修正文档映射。
- 不为满足文档创建空壳模块。
- 明确 webapp 与 workbench 的主次、兼容和退出策略。

### 验证

    $env:PYTHONPATH = "src"
    python -m unittest discover -s tests -p test_langchain_integration.py -v
    python -m unittest discover -s tests -p test_workbench.py -v
    python -m unittest discover -s tests -v
    python -m compileall -q src tests experiments scripts
    npm run format:check --prefix apps/web
    npm run build --prefix apps/web
    git -c safe.directory=D:/RAG/RepoLens diff --check

### 完成条件

- [ ] native、LangChain、CLI、Web、Compose 使用一致的当前模型名。
- [ ] 包版本与路线图阶段不再混写。
- [ ] 架构模块表与实际源码一致。
- [ ] 全量回归通过，冻结检索指标未改变。

## 6. M2：形成真实作品集历史

### 目标

让第三方可以审阅来源、运行 CI 和查看真实迭代。

### 审计命令

    git -c safe.directory=D:/RAG/RepoLens status --short --untracked-files=all
    git -c safe.directory=D:/RAG/RepoLens check-ignore -v data dist build src/repolens.egg-info apps/web/node_modules
    rg -n --hidden -g "!data/**" -g "!dist/**" -g "!build/**" -g "!.git/**" "API[_-]?KEY|BEGIN .*PRIVATE KEY|sk-[A-Za-z0-9]"

确认候选文件不含：

- API Key、env、token、私人凭证。
- SQLite、下载仓库、虚拟环境和缓存。
- 上游源码副本。
- 无法解释的二进制产物。

### Git 原则

- 不伪造 V1-V6 历史，不 backdate。
- 首次提交明确写为 audited initial import 或等价含义。
- 后续以真实小提交表达每个优化。
- commit 前展示候选差异和验证结果。

### 授权停点

完成审计后停止，询问用户：

1. 是否允许首次 commit。
2. 是否创建或关联远程并 push。
3. 采用何种许可证。Agent 不代替用户选择 MIT、Apache-2.0 等许可证。

### 完成条件

- [ ] 许可证已由用户选择，或明确保持未授权。
- [ ] 获授权后形成真实首次提交；未授权时记录阻塞。
- [ ] 干净 clone 可以构建，不依赖本机 data 目录。
- [ ] README 或 release 提供 commit、构建命令和限制。

## 7. M3：Docker、远程 CI 与发布

### 本地 Docker

先检查：

    docker version
    docker compose version
    docker compose config --quiet

Docker 不存在时记录阻塞，不自动安装。存在时执行：

    docker build --tag repolens:portfolio .
    docker compose up -d --wait --wait-timeout 120
    python scripts/container_smoke.py
    docker compose down

继续用 compose.repository.yml 验证只读 mount，并用 docker inspect 确认目标仓库 RW=false。

### 远程 CI

需要 M2 push 授权。至少验证：

- Windows/Linux 和 Python 3.12/3.13。
- wheel 构建、安装后 demo。
- LangChain 专项。
- React format、type、build。
- OpenAPI 一致。
- Playwright。
- 冻结检索重放。
- Docker build、启动和只读 mount。

不得通过删除测试、放宽 gold、无条件 skip 或忽略退出码制造绿色。

### 发布

tag、release 和上传 wheel 需要单独授权。发布说明包含：

- commit SHA、wheel SHA-256、Python/Node 版本。
- 本地与远程验收矩阵。
- 支持范围和未验收项。
- 不包含数据库、目标仓库和 API Key。
- Mock/fixture 不代表模型质量。

### 完成条件

- [ ] Docker build、health、Demo、只读 mount 实际通过，或记录环境阻塞。
- [ ] 获授权后至少一次远程 CI 全绿。
- [ ] 失败重跑保留根因记录。
- [ ] 发布产物在干净环境安装运行。

## 8. M4：多仓库外部盲测

### 目标

证明 RepoLens 不只对 Flask 和 Taskboard 有效。第一轮只测试已有 Python/Markdown 能力，不同时引入新语言。

### 仓库授权

不得自行下载。向用户请求三个至五个已授权、本地存在的 Python 仓库及固定 commit。要求：

- 规模、领域和目录结构不同。
- 不使用 all-in-rag、AgentGuide。
- 至少一个跨文件关系较多。
- 至少一个同时有文档和测试。
- 首次检索前固定完整 SHA。

在 docs/target-repositories.md 记录用途、commit、许可证和结果能否公开。不得公开私有源码。

### 数据集

每仓库至少 15 题，总计不少于 45 题。类别必须包含：

- 精确 symbol/file。
- 英文自然语言。
- 中文无代码标识符。
- 跨文件调用/import。
- history/commit。
- 应拒答或证据不足。

每题在首次运行前记录 id、仓库、commit、问题、类别、期望 file/symbol/line locator 和审阅说明。

首次运行前冻结 manifest，记录：

- 数据集 SHA-256。
- parser/index/query/retrieval policy hash。
- commit SHA。
- 题目数和 locator 数。
- 标注者与冻结时间。

冻结后不按结果修改题目或 locator；标注错误通过新版本和变更说明修正。

### 必须对照

- keyword。
- local TF-IDF vector。
- hybrid。
- graph。
- small-repository full-context；超过窗口时标记 unavailable。

### 指标

按总体、仓库、类别、逐题报告：

- file Recall@5/10。
- symbol Recall@5/10。
- locator/chunk Recall@5/10。
- MRR 和去重 nDCG。
- 零命中率。
- P50/P95 latency。
- 索引时间、索引大小、增量复用率。
- graph 相对 hybrid 的改善与回退。

### 决策门禁

- 不因一个小类别提升更换默认策略。
- 默认策略变化必须由冻结盲测支持，并公开所有回退。
- 不覆盖旧结果。
- graph 只改善跨文件题时保持 opt-in 或使用可解释路由。

### 完成条件

- [ ] 至少三个真实仓库和固定 commit。
- [ ] 至少 45 题和冻结 manifest。
- [ ] 五种策略同题对照，或说明 full-context 不可用原因。
- [ ] 报告失败案例和回退。
- [ ] 没有运行或修改目标仓库代码。

## 9. M5：真实模型回答与引用评测

### 授权停点

调用前确认：

- provider、模型和 endpoint。
- 最大请求数、token 和费用。
- 哪些仓库允许发送代码片段。
- Key 已由用户放入环境变量；Agent 不读取或回显 Key。

### Runner 要求

现有脚本不足时新增 scripts/run_generation_benchmark.py。它必须：

- 复用现有 pipeline，不复制检索和 citation 逻辑。
- 固定 snapshot、策略、模型、temperature/thinking 和预算。
- 支持断点续跑，避免重复付费。
- 保存 response hash、request id、usage、延迟和 canonical citations。
- 默认不保存完整 prompt 和未脱敏源码。
- 原始输出与人工 judgment 分开。
- 单题失败必须记录，不静默重试到成功。
- 重试、请求数和费用有硬上限。

### 对照实验

同题至少比较：

1. full-context。
2. keyword。
3. TF-IDF vector。
4. hybrid。
5. graph。
6. 新增 dense/reranker 后的独立实验臂。

每轮只改变一个主要变量，不同时修改 prompt、模型、检索、top-k 和预算。

### 人工审阅字段

- answer_correct。
- claim_supported。
- citation_valid。
- citation_entails_claim。
- should_abstain。
- actual_abstain。
- failure_type。

优先两名独立审阅者。只有一名时报告限制。标签绑定 response SHA-256。

### 指标

- schema/citation pass rate。
- answer accuracy。
- citation precision。
- claim support coverage。
- abstention precision/recall/F1。
- unsupported-answer rate。
- P50/P95 latency。
- input/output tokens 和单题成本。
- 分仓库、类别、策略结果。

### 完成条件

- [ ] 至少 30 个真实模型案例。
- [ ] 结果绑定人工标签、模型配置和 response hash。
- [ ] 至少一个 citation 合法但语义不支持的真实失败案例。
- [ ] README 不把 scripted fixture 当作真实模型质量。
- [ ] 未记录 Key、完整私有 prompt 或无授权源码。

## 10. M6：根据实验改进检索

只有 M4/M5 建立基线后开始。每项优化独立实验，失败结果保留。

### 10.1 Full-context 路由

- 统计可发送源码 token。
- 小仓库允许完整上下文实验。
- 保留文件边界和 canonical locator。
- 超出窗口时 fail closed 或回退检索。
- 比较准确率、延迟和成本。

### 10.2 Contextual chunk

检索表示可加入：

- repository-relative path。
- module/class/function qualified name。
- 函数签名。
- 最近的 class/module header。
- 有界 import/调用邻域摘要。

检索文本与引用原文必须分开，最终 citation 仍回到逐行校验的原始 evidence。

### 10.3 Dense embedding

必须先获依赖和数据外发授权。要求：

- 复用或窄化 EmbeddingProvider 接口。
- provider/version/dimension/normalization 进入 index policy。
- 本地和远程 provider 边界分开。
- 支持批处理、超时、缓存、失败回退。
- 保留 local-tfidf-v1 基线。
- 模型变化创建新 policy/snapshot，不能混用向量。

### 10.4 Reranker

- 只对固定候选池 rerank。
- 不扩大未记录上下文。
- 报告延迟、成本和逐题变化。
- top-k 不改变候选池语义。
- 盲测不支持时默认关闭。

### 10.5 Query 路由

可解释识别 identifier、history、cross-file、natural-language、Chinese。优先规则和可测试特征，不先增加黑盒模型。路由策略进入 manifest。

### 完成条件

- [ ] 每项只有一个主要变量。
- [ ] 报告质量、回退、延迟、成本和索引体积。
- [ ] 失败实验保留。
- [ ] 默认策略只由盲测证据改变。

## 11. M7：只读 MCP / Agent Context 接口

### 目标

让 RepoLens 成为外部 coding agent 的证据层，而不是重复实现完整 coding agent。

### 工具范围

- search_code。
- find_symbol。
- find_references。
- get_file_context。
- search_history。
- get_commit_diff。
- build_dependency_subgraph。
- get_evidence。

### 安全要求

- schema 封闭，禁止 additional properties。
- repository、snapshot、base/head 由宿主固定。
- 不提供 shell、写文件、网络、checkout、安装和测试执行。
- 数量、字节、节点、边、调用次数和 deadline 有上限。
- 每个结果带 snapshot/commit/path/symbol/line/evidence ID。
- 仓库文本不能改变工具权限。
- metadata-only 日志。
- 复用现有 validation，不复制宽松实现。

### 测试

- 非法版本和仓库参数被拒绝。
- path traversal、未来版本和跨 snapshot evidence 被拒绝。
- 仓库 prompt injection 不能新增工具权限。
- 超预算、重复、超时、损坏索引 fail closed。
- citation 能由 IndexStore.evidence 再验证。
- MCP 不启动网络或目标仓库代码执行。

### 完成条件

- [ ] 外部 Agent 能取得精确文件和行范围。
- [ ] 权限不超过 ControlledAgent。
- [ ] 有最小接入示例和威胁边界。
- [ ] 可选依赖不破坏标准库 CLI。

## 12. M8：多语言扩展

只在 M4/M5 完成后开始，不为了简历同时支持多种低质量语言。

1. 由用户根据岗位选择 TypeScript/JavaScript 或 Java。
2. 新建 ADR，对比标准库 parser、Tree-sitter、LSP/SCIP、自定义扫描。
3. 定义 file、symbol、range、imports、calls、inheritance、error 和 fallback 契约。
4. 先做 10 至 20 个 fixture，再做一个固定真实仓库盲测。
5. 所有 graph edge 有 provenance；无法唯一解析时保留 unknown。

完成条件：

- [ ] 独立 policy/version 和迁移规则。
- [ ] parser、incremental、evidence、graph、CLI/Web 有测试。
- [ ] 至少一个真实仓库评测。
- [ ] 报告 Python 回归、包体积和启动时间。

## 13. M9：维护性与质量门禁

1. 先测量最长文件、职责、依赖和测试覆盖，不立即重构。
2. 明确 webapp.py 与 workbench 的去留；未经授权不删除兼容入口。
3. 逐个评估：
   - src/repolens/webapp.py
   - src/repolens/index.py
   - src/repolens/impact.py
   - src/repolens/cli.py
   - apps/web/src/styles.css
4. 按稳定职责拆分，不按行数机械拆分。
5. 新增 Ruff、Pyright/Mypy、coverage、SBOM 或漏洞扫描前获得依赖授权。
6. 覆盖率优先发现 Git 安全、snapshot 隔离、citation、预算/超时、迁移和 API 权限风险，不追求空洞百分比。

完成条件：

- [ ] 入口职责明确。
- [ ] 新模块没有复制业务逻辑。
- [ ] 公共接口有类型检查，或记录不引入原因。
- [ ] CI 质量门禁不依赖大范围 ignore。

## 14. M10：README、演示与面试收口

### README 首屏必须回答

1. 解决什么问题。
2. 与全仓库长上下文和普通向量库 Demo 有何不同。
3. 三项最强可验证结果。
4. 三条命令内如何运行 Demo。
5. 最重要限制。

推荐结构：

    一句话定位
    演示 GIF/截图
    三个关键结果
    架构图
    快速开始
    为什么可信
    限制

### 必须展示

- 精确 commit/snapshot citation。
- graph 改善跨文件题但在通用题回退，因此不替换默认 hybrid。
- citation 合法但语义错误的真实案例。
- 无证据时 provider 调用前 abstain。
- 工具白名单、预算、超时和 Trace。
- 干净 wheel、Docker 和 CI。

### 禁止宣传

- 任意仓库准确率。
- 把 Recall@10 称为回答准确率。
- 全语言支持。
- 把本地单用户、无认证服务称为生产级。
- 把 LangChain adapter 验收称为准确率提升。
- 完全消除幻觉，或引用有效即答案正确。

### 五分钟演示

1. doctor：说明本地能力和依赖边界。
2. 导入固定 commit：展示 snapshot 和工作树隔离。
3. 搜索/问答：打开 commit/path/symbol/line evidence。
4. 无命中或伪造引用：展示 abstain/fail closed。
5. 影响分析或关系图：展示跨文件来源和 unknown。
6. 评测页：同时展示改善与回退。
7. Trace：展示工具白名单、预算和降级。
8. 主动说明多仓库、真实模型、Docker 和 CI 状态。

### 面试必答

- 为什么不直接用长上下文。
- TF-IDF 与 dense embedding 的区别。
- BM25、RRF、reranker 和 graph expansion 的职责。
- 如何防止未来版本泄漏。
- citation 合法为什么仍可能语义错误。
- 为什么不用任意 LangGraph Agent。
- 为什么 graph 不做默认。
- 如何证明没有针对 Flask 调参。
- vibecoding 中 AI 做了什么，作者承担了哪些设计和验收。
- 为什么下一步先做评测而不是继续加框架。

### 完成条件

- [ ] 新用户不读 progress.md 也能运行 Demo。
- [ ] README 首屏不被 V1-V6 历史淹没。
- [ ] 架构图与实际模块一致。
- [ ] 截图/GIF 不含私人路径、密钥或无授权源码。
- [ ] 每个指标能链接到固定数据集和结果。

## 15. 严格执行顺序

| 顺序 | 里程碑 | 原因 |
|---:|---|---|
| 1 | M0 当前基线 | 先确认现状 |
| 2 | M1 时效性与文档 | 消除明显错误 |
| 3 | M2 Git 历史 | 最大可信度缺口 |
| 4 | M3 CI/Docker/发布 | 把配置变成运行证据 |
| 5 | M4 多仓库盲测 | 证明仓库无关性 |
| 6 | M5 真实模型评测 | 区分验证器与模型质量 |
| 7 | M6 检索改进 | 根据失败数据优化 |
| 8 | M7 只读 MCP | 对接 agent 生态 |
| 9 | M9 维护性 | 收敛结构和门禁 |
| 10 | M10 面试收口 | 用已验证事实展示 |
| 11 | M8 多语言 | 高成本，最后决策 |

M8 可以推迟；多语言数量不是作品集完成条件。M7 是高价值加分项，未完成时必须列为路线图。

## 16. 里程碑交接模板

每次在 progress.md 顶部追加：

    ## YYYY-MM-DD：里程碑名称

    ### 已完成

    - 行为变化：
    - 修改文件：
    - 关键取舍：

    ### 验证

    - 确切命令：通过/失败，用时，测试数
    - 结果文件：
    - SHA-256：

    ### 限制与未执行

    - 未执行：
    - 失败/阻塞：
    - 不能据此声称：

    ### 下一步

    - 第一个安全可执行任务：
    - 需要用户授权：

最终回复必须包含结果、验证、限制、未获授权而未执行的动作和下一里程碑的第一个具体任务。

## 17. 完成定义

只有总体验收标准全部满足，并由用户确认发布范围后，本计划才算完成。在此之前，progress.md 必须持续区分：

- 已实现。
- 本地已验证。
- 远程或实机已验证。
- 只在 fixture 中验证。
- 真实模型已评测。
- 尚未执行或被授权阻塞。

RepoLens 最有价值的面试叙事不是使用了多少框架，而是版本隔离、可验证证据、失败关闭、受控 Agent，以及用冻结实验决定哪些能力应该成为默认值。
