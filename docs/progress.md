# 进度与交接

## 2026-10-22：M5 第二项：独立审阅模板与评分汇总

### 已完成

- 修复中断工作树中的重复拒答 TP 计数；拒答 precision/recall/F1 使用同一组 TP/FP/FN，零 TP 且存在误拒/漏拒时 F1 为 0，无分母时为 null。非法输出不算成功拒答，应拒答题中的非法输出计为 FN。
- 新增 `create_review_template`，复用原 schema/citation validator，为合法输出的 claim/citation pair 生成空白标签，所有 case 绑定确切 `output_sha256`。非法输出的 pair 留空但仍作为结构失败参与总分；未完成的 null 标签不能评分，不自动生成正确性/语义支持标签。
- 修复 CLI 模板模式：`--create-review-template` 与 `--judgments` 二选一，模板不再读取不存在的 judgment 文件；评分报告同时记录两份输入原始字节的 SHA-256，模板只记录 responses SHA-256。输出继续独占创建，不覆盖人工材料。
- 报告升级到 `repolens.generation-evaluation.v2`，增加拒答 F1、unsupported-answer rate、answerable/unanswerable 题数及 strategy/category 分组。unsupported-answer 明确定义为合法 answered 输出中至少有一个 citation 被标为 unsupported；不是跨仓库/真实模型质量结论。
- 修改范围：`generation_evaluation.py`、`scripts/evaluate_generation.py`、专项测试及 README/架构/生成评测/V6 使用说明。没有修改 runner、检索策略、冻结 gold、历史结果、provider、依赖或前端。

### 验证

- 环境：Windows，Python 3.12.8。`$env:PYTHONPATH='src'; python -m unittest tests.test_generation_evaluation tests.test_generation_benchmark -v`：18 项，17 通过、1 项 symlink 权限跳过，9.983 秒，退出码 0。日志 `data/m5-review-targeted-tests.log`，SHA-256 `db773f71f1480046ee469c45c4f45daa458a96c1c7ed980fca05ac89895c8a01`。
- `$env:PYTHONPATH='src'; data/v5-web-venv/Scripts/python.exe -m unittest discover -s tests -v`：223 项，222 通过、1 项 symlink 权限跳过，225.384 秒，退出码 0。包含可选 LangChain、Web/API、Agent/MCP 及 CLI；日志 `data/m5-review-full-tests.log`，SHA-256 `f22fd71eab04d557944162c04e000dee4c326ca961260f96bc043deb2e825aae`。
- `$env:PYTHONPATH='src'; python -m compileall -q src tests experiments scripts`、`python scripts/v6_regression.py`、`python scripts/project_audit.py --check-links --output data/m5-review-audit.json`、Web 环境的 `python scripts/export_api.py --check` 和 `git diff --check`：通过。46 个模块、76 个本地文档链接、无断链；冻结检查没有传 `--index`，不算 90 次实际检索重放。
- `$env:PYTHONPATH='src'; python scripts/build_release.py --output data/m5-review-package.json`：通过，退出码 0，3.891 秒。wheel SHA-256 `f2c93ca68c82b9d46c0e35437035d8406b9ba93c0ac76cd89c27a4d9d00809b0`，15 个前端资源一致、stale assets=0。首次漏设 PYTHONPATH 的构建在收尾 import 失败，修正命令环境后重跑，不改构建脚本掩盖失败。
- `python -m pip --python data/portfolio-polish-venv/Scripts/python.exe install --no-index --no-deps --force-reinstall dist/repolens-4.1.0-py3-none-any.whl` 后，以 `data/portfolio-polish-venv/Scripts/python.exe -I -m unittest discover -s tests -p test_generation_evaluation.py -v` 复验：8 项全部通过，0.019 秒，退出码 0。日志 `data/m5-review-installed-tests.log`，SHA-256 `3c0aeb81772b18eb1195790e686abbbcba520485301c35998c916b1d4e9489f6`。只离线安装当前项目 wheel，没有新增第三方依赖。
- 实际运行 `python scripts/evaluate_generation.py --responses eval/v6-generation-responses.json --create-review-template --reviewer fixture-review --output data/m5-review-template.json` 及 `python scripts/evaluate_generation.py --responses eval/v6-generation-responses.json --judgments eval/v6-generation-judgments.json --output data/m5-review-replay.json`：均退出码 0。五个 scripted 反例得到拒答 precision=0.5、recall=1、F1=2/3、unsupported-answer rate=0.5。报告 SHA-256 `d033c23bf2db3b5159d2f30a490ca3814c1bc5b96f57342e66e00d74f1bbb017`，仅是评分器契约，不是 DeepSeek 质量。

### 限制与下一步

- 本轮没有读取 API key、调用真实模型、发送目标源码、引入新依赖、索引学习参考仓库、改 LICENSE 或发布 tag/release。M4 继续暂缓；M5 仅完成评测工具准备，尚无真实模型固定题集加独立标签质量报告、费用硬门禁或多审阅者一致性分析。
- 已核实第一项提交 `ccdf2c9` 的 [CI 39731273779](https://github.com/Zhang-J1a/RepoLens/actions/runs/39731273779) 最终为 failure：5 个 job 成功；Windows Python 3.13 的 `test_impact_and_in_memory_settings` 在冷启动 impact 请求的客户端 10 秒超时，随后清理遇到 SQLite 文件仍占用。不能把该运行称为全绿；本轮未混入独立的兼容 Web 修复。本机本轮同用例与全量回归通过，不替代远程结论。
- 按用户既有授权，验收后提交并推送第二项，再核验新 CI。下一个安全任务是单独修复/验收上述 Web 冷启动与清理生命周期问题；真实模型评测须先确认 provider/model/endpoint、固定仓库源码外发范围及请求/token/费用上限。

## 2026-10-22：M5 真实模型评测执行器准备

### 已完成

- 在既有 `QuestionAnswerPipeline` 上增加显式 provider 入口：默认仍为离线 Mock，可选 `deepseek` 或 `langchain`；没有复制检索、上下文打包或 citation 校验逻辑。
- 固定 manifest 记录 provider、model、snapshot、commit、index corpus、策略、上下文/输出预算和 provider 最大重试次数；每题预算按最大尝试次数预留。
- 增加 `responses.json` 导出：完成事件只记录 evidence 定位和结构化 telemetry，导出时从同一 snapshot 恢复 evidence 正文，供独立人工评分器使用。输出与标签仍分离，未自动判定语义正确性。
- 真实 provider 运行仍受授权停点约束：本轮未读取 API key、未调用 DeepSeek、未发送仓库源码、未产生真实费用。M4 多仓库盲测继续按用户决定暂缓。

### 验证

- `$env:PYTHONPATH='src'; python -m unittest tests.test_generation_benchmark tests.test_generation_evaluation -v`：13 项中 12 项通过、1 项因本机无创建 symlink 权限跳过，9.454 秒，退出码 0。
- `$env:PYTHONPATH='src'; python -m unittest discover -s tests -q`：218 项通过、28 项按当前环境条件跳过，239.585 秒，退出码 0；跳过项属于可选依赖、平台能力或真实外部服务门禁，未改测试以制造全绿。
- `$env:PYTHONPATH='src'; python -m compileall -q src tests experiments scripts`：通过；`npm run format:check --prefix apps/web`、`npm run build --prefix apps/web`：通过。
- `$env:PYTHONPATH='src'; data/v5-web-venv/Scripts/python.exe scripts/export_api.py --check`：通过；同环境 LangChain 专项 11 项通过。`python scripts/project_audit.py --check-links --output data/current-audit.json`：46 个模块、76 个本地链接、无断链。
- `python scripts/build_release.py --output data/current-package.json`：wheel `repolens-4.1.0-py3-none-any.whl` 构建通过，SHA-256 `ce9dd22f360038e24459830874516a038c3a00f75d0ba2ed0f5340e269bd60cf`，15 个前端资源、0 个 stale assets。
- 本轮未调用真实 DeepSeek、未读取或保存 API key；`responses.json` 的源码正文导出只在显式调用 API 时启用，未生成或提交真实评测产物。
- `$env:PYTHONPATH='src'; python -m py_compile src/repolens/benchmark.py scripts/run_generation_benchmark.py`：通过；脚本 `--help` 已显示 `mock/deepseek/langchain` 三种 provider。
- `git diff --check`：通过。专项新增测试确认 journal 不包含源码正文，`responses.json` 可以恢复完整 evidence 并被现有生成评测器消费。

### 限制与下一步

- 尚未形成真实模型质量报告；仍需用户明确 provider/model/endpoint、最多请求数、token/费用上限和允许外发的固定仓库后执行。
- 下一项先补齐“真实评测结果的独立人工审阅输入与报告汇总”，完成后再提交并推送；本轮只完成执行器准备，不把 Mock 结果称为模型质量。

## 2026-10-20：修复 Windows CI 冷索引超时与兼容 HTTP 断连处理

### 已完成

- [运行 39376129214](https://github.com/Zhang-J1a/RepoLens/actions/runs/39376129214) 的 5 个 job 通过，Windows Python 3.13 job `118474568885` 失败：`test_graph_and_version_search_api_pin_selected_version` 在冷索引图查询上触发客户端 `timeout=10` 的 TimeoutError；客户端离开后，兼容 HTTP 服务先遇到 WinError 10053，再尝试发送 500 响应，产生第二次断连异常。未将失败称为全绿。
- 版本绑定用例先准备 base/head snapshot，然后通过 HTTP 检查固定版本与复用行为；客户端 10 秒超时保持不变，新增精确 snapshot 和 `index_action=reused` 断言。另一图问答用例明确检查 `index_action=created`，保留冷启动索引覆盖。这不是索引性能优化或生产 SLO 验收。
- 将兼容 JSON/HTML 响应的共有发送步骤收敛到 `_send_bytes`，遇到 BrokenPipe/ConnectionReset/ConnectionAborted 时关闭连接，不重发错误响应。新增真实请求处理类的 12 个断连子场景；主 FastAPI API、检索/gold 和模型边界未改。

### 验证

- `$env:PYTHONPATH='src'; data/v5-web-venv/Scripts/python.exe -m unittest discover -s tests -p test_webapp.py -v`：8 项通过，13.010 秒，退出码 0。日志 `data/portfolio-http-disconnect-tests.log`，SHA-256 `40B261E7BB5C869F48ADA32B0B7CAC88BF015F399ADF740BAC0031EB9559CDF8`。
- 重建并离线安装独立 wheel 后，清除 PYTHONPATH，以安装环境 `python -I -m unittest discover -s tests -p test_webapp.py -q` 运行同组：8 项通过，13.437 秒。日志 `data/portfolio-installed-http-tests.log`，SHA-256 `E35F0A8EF538FD05E91AA99218F60DEF4A1A950BFABB85C595BB406752EF5986`。
- 当前 wheel SHA-256 `ea70ac3ec563f6ca0cc6821c4b805687c4476b096dcf022e75405bc70a469959`，15 个前端资源匹配、stale assets=0。报告 `data/portfolio-http-fix-package.json`，SHA-256 `04D2A3C0A8E87E17431688AB1873D8C23C6E123F1D747FE7376FE8C3918D3487`。policy/view 冻结门禁和 OpenAPI check 均通过。
- 上一提交在最终本地完整环境执行 216 项：215 项通过、1 项因主机无 symlink 创建权限跳过，177.990 秒。日志 `data/portfolio-final-source-tests.log`，SHA-256 `7B8CDF29F6B6EA9825B9EA4AAC4518DA5DD9425CEFC95A6C6211C176E3DFD6C3`；Linux Python 3.12 CI 日志确认 symlink 用例实际执行为 ok（216 项、27 项可选依赖跳过）。这不是本次 HTTP 修复后的全量结果；当前测试数为 217。

### 限制与下一步

- 新断连测试首次错用没有 do_POST 的传输基类，6 个 JSON 子场景报 AttributeError；改为实际 RepoLensRequestHandler 后全部通过，未删除断言。
- 提交并推送本次修复，再核验新 workflow；没有增加超时、跳过失败用例或按结果修改预期证据。M4 仍暂缓，未调用真实模型或增加依赖。

## 2026-10-20：离线评测日志路径保护收尾

### 已完成

- 最后审查补充输出文件边界：manifest、events journal 与锁文件不能为符号链接或解析到输出目录之外，防止日志路径回指目标仓库。仍不承诺抵御恶意本机进程并发替换文件的完整文件系统沙箱。
- 新增临时仓库回归：journal 指向目标仓库文件时必须在写 manifest/lock 前拒绝，原文件保持不变。当前总测试数增加到 216；下方 215 项全量结果和全绿 CI 属于此次窄补强前的已验证实现。

### 验证

- `$env:PYTHONPATH='src'; python -m unittest discover -s tests -p test_generation_benchmark.py -v`：9 项中 8 项通过、1 项因本机无创建 symlink 权限跳过，7.389 秒，退出码 0。日志 `data/portfolio-benchmark-path-tests.log`，SHA-256 `4672BD1FD267F3E7C6CED1B500F0CA445B7ED80FCA2092F4FC90777D54B978BB`。
- 重新构建并离线安装当前 wheel，以 `python -I -m unittest discover -s tests -p test_generation_benchmark.py -q` 验证：同样 8 项通过、1 项跳过，7.449 秒；确认 `benchmark` 从独立环境 site-packages 加载且包含路径保护。日志 SHA-256 `16486D55652582F31F5254EF2EF131E24492B29D22E4C119A4C3BE094E24865B`。
- 当前 dist wheel SHA-256 `31a403edca2f97ca8eb17c3cbe604cedde5a720597a012eb891c66b702c939b6`，15 个前端文件匹配、stale assets=0。报告 `data/portfolio-path-guard-package.json`，SHA-256 `8A41046368039F238A0ACA48A20E067F03357147B6A67A54AC49AC02FD92E290`。

### 限制与下一步

- 本机 symlink 用例的跳过不算实际链接保护验收，交由 Linux CI 真实执行；推送后检查完整新 workflow。未安装新依赖、修改检索/gold、运行目标代码或调用真实模型。
- README、简介、主题和纵向 Mermaid 已在 GitHub 页面核验；M4 继续暂缓，后续重点为 M5 安全审阅导出和 MCP 第三方客户端互操作。

## 2026-10-20：暂缓 M4，完成 GitHub 展示、维护性与只读接口切片

### 已完成

- 用户明确暂缓 M4 选仓/盲测，授权先按文档收口、维护性审查、关键测试、离线模型评测准备及 MCP 顺序推进，并整理 GitHub/README。此为执行顺序调整，不将 M4/M5 或整个优化计划标为完成；原学习参考边界、默认 hybrid 与冻结 gold 保留。长期决策见 ADR 0026。
- 重写 README 为定位、实际工作台截图、快速开始、同条件检索对照、架构、边界和文档导航；移除依赖本机旧 venv/wheel 的主流程。新增 `docs/usage.md`、CONTRIBUTING、SECURITY、Issue/PR 模板与项目链接，部署/V6 验收同步真实全绿运行，面试文档补充当前状态。不添加 LICENSE。
- GitHub 页面已保存简介、使用文档链接、9 个技术主题（rag/code-search/python/fastapi/react/langchain/mcp/static-analysis/git），隐藏空 Releases/Packages 侧栏。没有创建 release、发布包或修改仓库权限。
- M9 先核对五个大文件的职责和静态依赖，再将纯 Markdown renderer 提取到 `impact_rendering.py`，保持函数源码逐字一致并保留 `impact.render_impact_markdown`。`impact.py` 从 600 行变为 522 行；兼容入口、事务和检索边界保留。标准库审查脚本与 CI 本地文档链接门禁见 `docs/maintenance-review.md`。
- 新增真实 Git fixture 测试，验证 hook/smudge filter 不执行及 replace refs 不能替换固定源码/历史；不运行用户目标仓库代码。
- M5 准备：仅 Mock 的 `benchmark.py` 和执行脚本，冻结题集/实现/policy/snapshot/corpus/预算，fsync 预留日志、失败脱敏、恢复不重复已开始任务，校验输出 hash 和并发锁。结果不含完整 prompt/源码正文；真实调用、费用硬上限和语义评测仍待后续切片。
- M7 最小切片：标准库 stdio MCP 2025-06-18，复用现有受控工具/证据校验/spawn 超时，提供 8 个宿主固定版本的只读工具，包括 get_evidence。逐次/累计结果、字节、调用数及 deadline 有上限，无任意 repository/snapshot/shell/URL 参数。真实子进程握手与 canonical evidence 读取已验证，第三方客户端互操作未验收。
- 四个提交已推送：`d89e1c4`（M4 输入与候选核验）、`53d8ca9`（渲染隔离与 Git 安全）、`7b26461`（MCP 与离线评测日志）、`a1893aa`（README 与使用文档）。对应新 CI 运行 `39374918498` 已完成并全部成功。

### 验证

- `$env:PYTHONPATH='src'; .\data\v5-web-venv\Scripts\python.exe -m unittest discover -s tests -v`：215 项、零跳过、全部通过，unittest 182.196 秒，退出码 0。日志 `data/portfolio-polish-tests.log`，SHA-256 `C4F334145765A8628CC8F2EE7A2A5388B403424A4B1F46FBA621F1C1D870A828`。
- MCP 源码专项 10 项通过（13.728 秒）；离线 benchmark 最终 8 项包含在全量测试；既有 impact 6 项通过，提取前后 renderer AST 源段逐字相同。后续只移除 renderer 文件末尾多余空行，staged whitespace 检查通过；不改变函数内容。
- `python scripts/project_audit.py --check-links --output data/portfolio-delivery-audit.json`：46 个运行模块、75 个常见本地 Markdown 链接、无断链。报告 SHA-256 `77E560AB024F581FBF63B8AC99A91F55D5847D5D54F219FEBF8A52827CA6593E`。只检查常见 inline link 的文件存在性，非 CommonMark/锚点/远端 URL 验证；静态测试导入不当动态覆盖率。
- `$env:PYTHONPATH='src'; python scripts/v6_regression.py`、Web 环境的 `python scripts/export_api.py --check`、`python -m compileall -q src tests experiments scripts`、TOML/YAML 解析、`git diff --check`：均通过。冻结校验本轮未传 `--index`，没有将其称为 90 次实际检索重放。
- `python scripts/build_release.py --output data/portfolio-delivery-package.json`：独立安装验收 wheel SHA-256 `f856ce58da13c9017f4b8f931458807449ff13ceaa2c9830b76135c9a57aa8bb`，15 个前端资源全部匹配、stale assets=0。构建报告 SHA-256 `218D3B4EA5789F9BF25915748A0997ED591398FE65341348A5BEA2E367B3F608`。
- 新建无 pip 的 `data/portfolio-polish-venv`，用已有 pip 的 `--python ... install --no-cache-dir --no-deps --no-index` 离线安装本项目 wheel；未安装新依赖。清除 PYTHONPATH 后，安装包 `python -I -m repolens doctor` 和 `python -I scripts/demo.py` 通过，后者验证工作树不变、临时文件清理。
- 上述 wheel 安装后执行 `data/portfolio-polish-venv/Scripts/python.exe -I -m unittest discover -s tests -p test_mcp.py -q`：10 项通过，15.141 秒，退出码 0。日志 `data/portfolio-delivery-installed-mcp-tests.log`，SHA-256 `3F0D57F02CAA9C6E365B2772D5D5E4D4BC35CDCEA4836BB453BA70AC20828CBA`。
- 最后一次清理合成预检测试中的路径字面量，避免把真实候选目录作为示例提交；M4 预检 11 项重跑通过，0.130 秒。33 个候选文件的 credential pattern 与禁止产物路径扫描均为零命中。
- GitHub API 确认 [CI 39374918498](https://github.com/Zhang-J1a/RepoLens/actions/runs/39374918498) 对应 `a1893aa2b5fb5ef863e2b8ca4b81b0c827f7ce56` 为 completed/success，六个 job 全绿，包括 Windows/Linux Python 3.12/3.13、LangChain 和完整 workbench/Docker。
- GitHub 实际页面核验：新 README 的徽章、工作台截图、导航和 Mermaid 均成功渲染；简介/文档链接与 9 个主题已保存。横向图节点较密，最后将其改为纵向分支并加入 MCP 路径；这次收尾只改 README/验收文档，未再改运行代码。
- README 收尾后重建 `data/portfolio-readme-final-package.json`：当前 dist wheel SHA-256 `e1da4aa9ef1634490b660e12bb09338e2e0fe1a3c3d9333fa9581e3b4d99285a`，报告 SHA-256 `3154C019C2B91F822BA85079B26302E87A9791A492323930CB81D712DCC334F1`。程序与静态资源 65 个文件与上述已安装测试版本逐字节一致，差异限打包元数据/README；76 个本地文档链接再次检查，无断链。没有为文档改动重复全量本地测试。

### 限制与未执行

- 新增 Git fixture 的首次专项有 1 项失败：required filter 未配置 clean，连 fixture 自身的 Git status 都拒绝执行。补充无副作用的 `clean=cat` 后，两项新增测试及全量回归通过；未删除断言或绕过检查。
- 本机仍无 Docker；本轮前端源码没有修改，未重复本机浏览器/Docker 验收。实际浏览器/容器验收来自本轮新 CI `39374918498`，不与历史运行 `39273995176` 混称。
- M4 选仓和外部盲测暂缓；未 clone hello-agents、未索引学习参考项目或新增真实目标，未读取 Key、调用真实模型、安装新依赖、授予开源许可或发布 tag/release。
- M9 没有动态覆盖率/外部类型检查器门禁，M5 没有真实付费 provider/计费硬限制/自动语义标注，M7 没有官方 SDK/第三方客户端互操作、HTTP、并发取消或完整协议覆盖。最小切片通过不能表述为这些里程碑全项完成。

### 下一步

- 本轮功能提交和 GitHub 页面已验收。最后的 README 图布局/验收链接更新另作 docs 提交，不影响已通过的程序行为；推送后仍检查该提交的 workflow 状态。
- 后续先推进 M5 日志到独立审阅输入的安全导出及 MCP 客户端互操作；真实模型、费用/源码外发、新依赖继续分别确认，M4 按用户决定暂缓。

## 2026-10-20：M4 候选仓库只读核验与开发集排除

### 已完成

- 用户提供 `Book Manager V1`、`HSI-SVM`，随后补充 `Hyperspectral-classification-deeplearning` 的本地路径。用户同时明确确认：`AgentGuide` 与 `all-in-rag` 保持仅学习约定，不用于 M4；允许公开最终选定仓库的名称、固定提交号和评测结果，不公开源码和本机路径。
- 三个所选路径均为独立 Git root。通过现有只读 `GitRepository` API 解析 HEAD、tree inventory、至多 100 条历史，并比较操作前后的 tracked status；三者状态均保持一致。未读取目标源码、密钥或 env 内容，未建索引、检索、运行目标代码或测试。
- `HSI-SVM`：HEAD `616a42249247db5c7008e9825a6e2543b1400960`，24 个常规 tracked 文件、13 个 Python 文件（39,844 字节）、1 个 Markdown、11 条可读本地历史；未发现常规测试路径或许可证文件，许可暂记 `NOASSERTION`。
- `Hyperspectral-classification-deeplearning`：HEAD `5b8641c2cf16f473393fc0cdd39475c3520c8e4d`，38 个常规 tracked 文件、6 个 Python 文件（33,768 字节）、2 个 Markdown、5 条可读本地历史；未发现常规测试路径或许可证文件，许可暂记 `NOASSERTION`。
- `Book Manager V1`：HEAD `1e747f22254a254fbf90d1a2631165e79a675a4d`，5 个 Python 文件、1 个 Markdown、2 条历史。本文件既有 V4.0.3/V4.1.0 记录证明它已用于中文检索开发验证，因此只作回归对象，不算新的盲测仓库。
- 将上述固定 SHA、许可限制和候选/排除状态记录到 `docs/target-repositories.md`，其中不包含本机路径。更新 M4 协议与预检排除规则，覆盖 Book Manager 的名称及声明路径，防止仅改计划中的仓库 ID 就误计为新盲测对象。
- 用户另补充 `hello-agents-1.0.3` 本地目录。目录存在但没有 `.git`，安全 Git wrapper 无法解析仓库/HEAD；只检查顶层名称、README 中的 `datawhalechina/hello-agents` 上游链接及本地 `LICENSE.txt`（CC BY-NC-SA 4.0）。尚无完整 Git SHA，不能因目录名含版本号就计入 M4。没有在目标目录初始化 Git 或修改文件。

### 验证

- 设置 `PYTHONPATH=src`，通过内联 Python 依次执行 `GitRepository(path)`、`commit('HEAD')`、`inventory(commit.sha)`、`history(commit.sha, max_count=100)`；前后各执行既有安全 Git wrapper 的 `status --porcelain=v1 -z --untracked-files=no`。两批核验命令均退出码 0，三个 root 匹配请求路径、tracked status 前后相同。未跟随 symlink 读取目标文件，未联网获取 Git objects。
- `$env:PYTHONPATH='src'; python -m unittest discover -s tests -p test_m4_preflight.py -v`：11 项通过，0.143 秒，退出码 0。日志 `data/m4-repository-screening-tests.log`，SHA-256 `6186798C6299AF9023287B9D01AAFAC91FD38D2C6C9D5D01368C786ACC9B9F9D`。
- `$env:PYTHONPATH='src'; python scripts/v6_regression.py`：退出码 0，冻结 policy/view 契约通过；本轮未传 `--index`，没有重放真实检索。
- `python -m compileall -q experiments/m4_preflight.py tests/test_m4_preflight.py`、`git -c safe.directory=D:/RAG/RepoLens diff --check`：均通过。
- hello-agents 目录核验内联命令退出码 0，结构化结果为 `not_eligible_yet`、`git_marker_exists=false`；底层 Git 失败如实作为不合格状态记录，不计为固定 snapshot 验收通过。`Test-Path -LiteralPath 'D:\RAG\RepoLens\data\repositories\hello-agents'` 为 False，可用于后续获授权后的独立 Git 副本，不覆盖用户源码目录。

### 限制与未执行

- 当前仅两个新候选，尚不足三个；两者均属高光谱分类领域，目录/规模差异和源码/关系仍待审阅。常规测试路径按 `test/tests`、`test_*.py` 和 `*_test.py` 初筛为零，不代表已对所有测试内容作人工结论。
- 未发现 license/licence/copying/notice 文件，不等于已确认其他位置不存在许可声明；只读评测授权及元数据公开授权不授予源码再分发许可。
- 未标注或冻结真实题集、未运行 M4 benchmark、未调用真实模型、未下载目标、未执行目标代码、未修改学习参考项目、未 commit/push。现有未提交准备工作保留。

### 下一步

- 已请求用户再补至少一个不同领域、同时有文档和测试的本地 Python Git 仓库。沿用已确认的元数据公开范围，无需重复询问。
- 对 hello-agents，可请求用户明确授权从 README 对应上游获取独立 Git 副本，先核实 1.0.3 对应 tag/ref 再固定完整 SHA；找不到对应版本时不静默改用 main。规划禁止自行下载，因此本轮未 clone；获取后仍须核验 Python/文档/测试、许可与盲测资格，不能提前计入合格数量。
- 收到路径后只读核验 Git/SHA、Python/文档/测试和许可，确认至少三个合格目标，再按 M4 协议审阅源码、标注 gold、实现和验证 runner，首次检索前冻结 manifest。

## 2026-10-20：M4 外部盲测输入预检与协议准备

### 已完成

- 核对 `main` HEAD 为 `39e2859bde3b04188cf6fadc9f5e4bf69867b01b`，开始前工作树干净。按计划从已验收的 M3 进入 M4 准备阶段，没有跳到检索调参、多语言或新框架。
- 新增 `experiments/m4_preflight.py`：只读计划 JSON/题集 JSONL，检查 3–5 个声明的 Python 外部仓库、完整 SHA 格式、授权/公开范围字段、每仓库至少 15 题、六类覆盖、全局题目 ID、版本绑定及源码/历史/拒答 gold 结构。返回输入字节 hash；不打开目标 Git、不建索引、不检索、不写文件。
- 新增中文 `docs/evaluation-m4.md`、空白 `eval/m4-input.example.json` 和 10 项离线合成契约测试，更新既有数据集说明和仓库清单入口。模板不能直接通过，避免把示例或 fixture 当真实盲测。正式含本机路径的输入计划应保存在忽略的 `data/m4/`。
- 区分源码 locator、历史提交和拒答 gold；明确 file/symbol/locator 分母、历史题与拒答题分开报告，full-context 作为回答对照，不冒充检索排名。现有 `evaluation.py`、默认 hybrid、冻结 gold 和历史结果均未改。
- 自检修正预检的排除规则：只检查仓库标识及声明路径末段，不能因为新目标存放在 `RepoLens/data/` 下而误拒；新增回归覆盖。真实规范 root、别名、仓库内容、许可、语义和授权仍须在正式输入确认后核验。

### 验证

- `$env:PYTHONPATH='src'; python -m unittest discover -s tests -p test_m4_preflight.py -v`：10 项通过，unittest 耗时 0.122 秒，退出码 0。日志 `data/m4-preflight-tests.log`，SHA-256 `4A4182B74D191AE20C2FBD169903446FB13A9D137A7223B43F55E7840BCB5EE8`。
- `$env:PYTHONPATH='src'; python -m unittest discover -s tests -p test_evaluation.py -v`：10 项通过，unittest 耗时 7.975 秒，退出码 0。日志 `data/m4-existing-evaluation-tests.log`，SHA-256 `51C9BE7F4AE643177B57818925A7A5281751153EE1C857A7276EE4A35A439163`。
- `$env:PYTHONPATH='src'; python scripts/v6_regression.py`：退出码 0，原始策略及三个窄扩展、6 个冻结视图和 90 条历史评测记录的 hash/契约通过。本轮没有传入 `--index`，因此不称本轮重新执行了 90 次检索。
- `python -m compileall -q experiments/m4_preflight.py tests/test_m4_preflight.py`：退出码 0。
- `$env:PYTHONPATH='src'; python -m experiments.m4_preflight --plan eval/m4-input.example.json`：按设计返回 `input_rejected`、退出码 1，空模板未被当成有效输入。
- `git -c safe.directory=D:/RAG/RepoLens diff --check`：通过。改动限于 M4 实验预检、专项测试、输入模板及文档，未改运行时、前端或依赖；本轮未重复全量/Web/容器验收。

### 限制与未执行

- 当前没有用户提供的 3–5 个新本地 Python 目标。规划第 8 节明确“不得自行下载。向用户请求三个至五个已授权、本地存在的 Python 仓库及固定 commit”，已请求用户给路径和评测元数据公开范围；SHA 可在收到路径后只读解析，无需用户手工查询。
- `input_shape_validated` 只证明声明/题集结构，报告中 `benchmark_ready` 始终为 false。配置中授权、external_blind 和 license 不能代替用户授权、许可核验和人工审阅。
- 未完成真实仓库登记、题集标注/语义审阅、source/history 验证、冻结 manifest、M4 执行与分层评分 runner 或 full-context 可用性审计；不声称 M4 完成或跨仓库质量提升。
- 未下载新仓库、访问/索引学习参考项目、调用真实模型、读取 Key、增加依赖、添加 LICENSE、commit/push 或发布 tag/release。本轮保留为可审阅工作树。

### 下一步

- 收到用户提供的 3–5 个本地 Python Git 仓库路径及元数据公开范围后，先只读核验规范 root、HEAD/commit、Python/文档/测试目录及许可证据，登记固定 SHA；人工标注每仓库至少 15 题，再实现/验证 M4 runner、校验 locator/history，并在首次检索前冻结 manifest。
- full-context 若涉及真实模型或源码外发，仍须按 M5 的 provider、允许仓库和预算停点确认；未获授权时如实记录 unavailable。

## 2026-10-19：M3 修复 CI 并完成全绿验收

### 已完成

- Agent snapshot root 校验先将宿主提供的仓库路径 `resolve(strict=True)`，再与索引中的规范 root 及固定 commit 比较。Windows 等价路径别名可以通过；不同 root/commit 仍以 `snapshot_binding_failed` fail closed。回归覆盖 `repo/../repo` 别名和错误 root。
- Compose 宿主端口可由 `REPOLENS_HOST_PORT` 覆盖，开发默认仍为 `127.0.0.1:8770`；CI 从 loopback 申请空闲端口，两个容器 smoke 共用该端口。
- 容器可选挂载用的合成 fixture 根目录原由 `tempfile.mkdtemp()` 以 `0700` 创建，非 root 容器用户不能遍历。CI 只将此合成目录设为 `0755`，挂载保持 `read_only: true`，并实际检查导入及 `RW=false`。没有更改用户仓库权限或应用数据路径策略。
- 冻结策略原清单正确阻止了 `agent/tools.py` 的哈希变更。新增 `eval/v6-agent-path-policy-manifest.json` 和显式 `--freeze-agent-path-policy` 流程，只覆盖该文件并校验父 V6 policy SHA 和当前实现 SHA；原始 policy、LangChain/provider 扩展、gold 与冻结结果均未改。

### 验证

- 最新 GitHub Actions run [`39272938696`](https://github.com/Zhang-J1a/RepoLens/actions/runs/39272938696)，head `90a81e88ac00261bbba6ff5ee3b77b5cba00e9f0`：六个 job 全部成功，包括 Windows/Linux Python 3.12/3.13、LangChain，以及 workbench/browser、Docker build/start、内置 Demo、挂载 Git 预检和只读挂载导入。
- 最新源码构建 wheel 后安装到干净隔离环境运行 `$env:PYTHONPATH` 未设置的 `python -m unittest discover -s tests -v`：184 项通过，27 项因核心 wheel 未安装可选 Web extras 按设计跳过，用时 136.762 秒。此 wheel 包含 Agent root 规范化及正/负向绑定断言。
- `test_graph.py` 20 项、`test_agent.py` 18 项、`test_workbench.py` 8 项、`test_v6.py` 14 项均通过；新增路径别名测试通过。
- `python scripts/v6_regression.py` policy/frozen-view contract 通过；`python scripts/v6_regression.py --index data/v4-flask-index` 固定 90 题回放通过，query error 为 0，未改检索策略或 gold。
- `python scripts/export_api.py --check`（`data/v5-web-venv` + `PYTHONPATH=src`）、`python -m compileall -q src tests experiments scripts`、`npm run format:check --prefix apps/web`、工作流/Compose YAML 解析、`git diff --check` 均通过。
- GitHub Actions 证明远程 Docker 与只读挂载通过；本机未安装 Docker，因此没有声称本机 Docker 已运行验收。

### 限制与未执行

- 没有调用真实 DeepSeek、添加 LICENSE、发布 tag/release 或上传 wheel。冻结检索通过不代表真实模型回答质量或跨仓库盲测已完成。
- 本机 Docker 仍未安装；容器验收来自 GitHub-hosted runner。学习参考项目未修改、运行或索引。

### 下一步

- 按路线图进入 M4：先请求用户提供已授权、已存在于本机且固定 commit 的多个 Python 仓库，再冻结题集后开展外部盲测。
- tag/release 与真实模型调用仍须分别遵守原授权停点。

## 2026-10-19：M2 公开推送授权与干净源码验收

### 已完成

- 首次本地根提交为 `9a2a5f6cd733caa5886fb6dfd12efa698c73ac74`，消息为 `chore: audited initial import of RepoLens V6`，包含 230 个文件，无父提交；提交后工作树干净。
- 用户进一步明确授权创建公开的 `Zhang-J1a/RepoLens` 并推送，继续保持不添加 `LICENSE`；没有授权 tag、release 或上传 wheel。仓库已由用户创建为空仓库。
- GitHub connector 与 Git 凭据管理器均确认账号 `Zhang-J1a`。创建远程前的 connector 查询返回 404，随后用户自行完成创建；本机凭据管理器查询未输出凭证内容。
- `git push --set-upstream origin main` 成功。GitHub API 确认仓库为 public、默认分支为 `main`，远端完整 SHA `4ea326a1cfadf969a46d62e132d242def21160e7` 与本地一致。
- 从已提交源码创建本地干净 clone，使用全新无 pip 的虚拟环境安装独立核心 wheel，doctor 与合成 Demo 均通过；clone 不包含原工作区 `data/`。README 补充首次提交、源码构建命令、许可证决定及核心/Web 验收边界。

### 验证

- `git -c safe.directory=D:/RAG/RepoLens log -1 --format="%H%n%P%n%s"`、`status --short --branch --untracked-files=all`、`ls-tree -r --name-only HEAD`：确认根提交、230 个文件及干净工作树；`Test-Path LICENSE` 为 False。
- `git -c safe.directory=D:/RAG/RepoLens -c core.whitespace=cr-at-eol show --format= --check HEAD`：通过；提交路径无 env、数据库、venv、构建产物或密钥文件。
- `git -c safe.directory=D:/RAG/RepoLens clone --no-local --no-hardlinks D:/RAG/RepoLens data/portfolio-m2-clean-clone`：通过，仅克隆本项目的本地提交。
- 在干净 clone 执行 `python -m pip wheel . --no-cache-dir --no-deps --no-build-isolation --no-index --disable-pip-version-check --wheel-dir ../portfolio-m2-core-wheel`：通过，退出码 0；独立核心 wheel SHA-256 为 `94c33c4a984fcf9329cceb61cc90c00333f4952098dc197943a4a456a6f7ff6b`，未覆盖现有完整 Web wheel。
- `python -m venv --without-pip data/portfolio-m2-clean-venv`、`python -m pip --python data/portfolio-m2-clean-venv/Scripts/python.exe install --no-cache-dir --no-deps --no-index --disable-pip-version-check data/portfolio-m2-core-wheel/repolens-4.1.0-py3-none-any.whl`：通过，退出码 0，没有安装第三方依赖。
- 在干净 clone 执行 `..\portfolio-m2-clean-venv\Scripts\python.exe -I -m repolens doctor` 和 `..\portfolio-m2-clean-venv\Scripts\python.exe -I scripts/demo.py`：均通过，退出码 0；Python 3.12.8、Git 2.53.0、SQLite FTS5 正常，Demo 9 文件、28 符号、39 chunks，工作树不变。

### 限制与未执行

- 第一次 wheel 构建因默认 pip cache 不在可写范围而失败；添加 `--no-cache-dir` 后重跑成功。最初的后续安装也因 wheel 尚不存在而失败；成功构建后重新安装通过，失败不计作通过。
- 干净源码构建只验证核心 CLI，不代表完整 Web、远程 CI、Docker 或真实模型质量。该副本固定在上述首次提交，README/本交接的文档变更不改变运行代码。
- 首次推送触发 GitHub Actions run `39265075552`（[workflow 记录](https://github.com/Zhang-J1a/RepoLens/actions/runs/39265075552)，head `4ea326a1cfadf969a46d62e132d242def21160e7`），最终 conclusion 为 `failure`：Ubuntu Python 3.12/3.13 与 LangChain job 通过；Windows Python 3.12/3.13 在 `test_agent_subgraph_exposes_bounded_nodes_and_edges`（`tests/test_graph.py:235`）以 `AgentStop: snapshot_binding_failed` 失败；workbench 的格式、构建、API、浏览器、冻结回归和 Docker image build 通过，但容器启动因 runner 的 `127.0.0.1:8770` 已占用而失败，后续只读挂载步骤跳过。未删除测试或放宽门禁。
- 一次本地 `git ls-remote` 因 Windows 凭据 helper 无可用凭据失败；通过 GitHub API 读取 branch/main 已核实远程 SHA。未读取或回显凭证，未调用真实模型，未下载、索引或运行学习参考项目。

### 下一步

- 进入 M3：复现并修复 Windows 图子图测试的 snapshot 绑定失败；隔离 CI 容器 healthcheck 的宿主端口冲突，并重新跑完整 workflow。保留失败根因，不删除测试或放宽门禁。
- M3 同时记录本地 Docker 未安装的环境限制；不自动安装，不发布 tag/release。

## 2026-10-19：M2 首次提交审计与授权

### 已完成

- 初审发现 230 个待跟踪候选；此前没有已跟踪文件、`HEAD` 或 remote。Git author name/email 已配置，未发现自定义本地 Git hook。
- `.gitignore` 明确排除 `data/`、`dist/`、`build/`、`*.egg-info/` 和 node_modules。候选路径检查无 symlink、SQLite、虚拟环境、wheel、可执行文件或密钥文件；仅有 5 个 PNG，均为工作台演示截图。
- 凭证格式扫描只命中 `tests/test_agent.py` 内 3 个明确用于错误脱敏断言的假 key 字符串；长凭证赋值扫描为 0。没有发现真实 key、env 文件或私钥。
- 已查看 5 张交付截图；发现的 workspace 本机路径已由 Playwright 脱敏重生成，并通过 1 项截图用例。历史评测 JSON 和 frozen gold 未修改。
- 230 个候选已暂存；没有未暂存或剩余未跟踪文件。暂存清单中没有 `.env`、数据库、venv、构建产物或其他可执行二进制。
- 用户明确选择“暂不添加 LICENSE”，并授权直接提交。使用已配置的 Git 身份，以 `chore: audited initial import of RepoLens V6` 形成真实首次提交，不回填日期或伪造 V1-V6 历史。
- GitHub connector 已核实登录账号为 `Zhang-J1a`；该账号下目前只查到 `paper_manager`，本地尚无 remote。远程提交还需确定 RepoLens 仓库及可见性。

### 验证

- `git -c safe.directory=D:/RAG/RepoLens status --short --untracked-files=all`：230 个未跟踪候选。
- `git -c safe.directory=D:/RAG/RepoLens rev-parse HEAD`：预期失败，仓库尚无提交；无 remote。
- `git -c safe.directory=D:/RAG/RepoLens check-ignore -v data dist build src/repolens.egg-info apps/web/node_modules`：所有生成目录均命中忽略规则。
- `git -c safe.directory=D:/RAG/RepoLens -c core.whitespace=cr-at-eol diff --cached --check`：通过。仓库按 `*.json -text` 保留 JSON 原始 CRLF 字节；对应冻结 manifest 与 M0/M1 回放文件的 index blob hash 均与工作区一致。

### 限制与未执行

- 按用户决定保持没有 `LICENSE` 文件，不授予开源许可。本条记录随首次本地提交保存，提交后的 SHA、根提交和工作树状态由 Git 命令复核。
- 尚未 push；没有将项目写入无关的 `paper_manager` 仓库，也没有创建远程仓库。
- 真实模型、Docker 和远程 CI 仍未授权/未验收。

### 下一步

- 复核暂存差异并完成已授权的首次本地提交；随后验证根提交、文件数、干净工作树及 `LICENSE` 不存在。远程 RepoLens 仓库名/地址和公开或私有可见性确定后，再关联并推送。

## 2026-10-19：作品集优化 M1 时效性与文档对齐

### 已完成

- DeepSeek 当前默认模型改为官方推荐名 `deepseek-flash`；CLI help、Compose、README 和对应 provider 测试同步。Web 与 LangChain adapter 继承同一默认值。包版本仍为 4.1.0，路线图阶段仍为 V6。
- README 明确区分包版本与路线图阶段，并说明 V5 工作台、当前 V6 主工作台及保留的标准库兼容入口。架构表移除不存在的 `workflow.py`/`validation.py` 模块条目，将职责映射到实际 `cli.py`、`pipeline.py`、`answer.py`、`config.py`、`agent/` 和 `workbench/schemas.py`。
- 冻结门禁最初因 `provider.py` 纳入原始 policy hash 而正确拒绝变更。为不覆盖原 V6/LangChain manifest 或 gold，新增 `eval/v6-provider-model-policy-manifest.json`，仅允许覆盖 `src/repolens/provider.py`，并验证它仍为原策略的子清单。扩展清单 SHA-256 `7207D51AF93B2358ADAB3ABFA7E891D19B22D00416DF0DBEC5A2F022A1DFB5B0`。
- 工作区演示截图检测到本机绝对路径；Playwright 截图流程现在替换并断言通用示例路径，重新生成的 `docs/screenshots/v6/workspace-desktop.png` 不再暴露本机路径。

### 验证

- 专项：`test_langchain_integration.py` 11 项通过；`test_workbench.py` 8 项通过；`test_v2.py` 26 项通过。
- 全量：`$env:PYTHONPATH='src'; .\data\v5-web-venv\Scripts\python.exe -m unittest discover -s tests -v`：184 项通过，测试耗时 156.542 秒，退出码 0；完整日志 `data/portfolio-m1-tests.log`，SHA-256 `C197D41405551C5C32D3449951EE05478A3251A6A088872743E848E34AF7DB20`。PowerShell 管道总耗时 159.076 秒。
- `python -m compileall -q src tests experiments scripts`、`python scripts/export_api.py --check`、`npm run format:check --prefix apps/web`：均通过。
- `npm run build --prefix apps/web`：通过，退出码 0，15 个静态资源进入构建；既有 Monaco 编辑器 chunk 约 3.69 MB 的 Vite 提示仍存在。
- `python scripts/v6_regression.py --index data/v4-flask-index --output eval/portfolio-m1-retrieval.json`：90 次固定索引查询通过，query error 为 0。与 M0 报告逐组逐项比较，6 组 × 7 项 Recall/MRR/nDCG/数量/错误指标完全一致；耗时指标按机器运行波动。报告 SHA-256 `0F8807B53DD142A3268558DF23EA2A6F37AB18271673D8F0E5AE10187C06B363`。
- Playwright 工作区导入与截图用例：1 项通过、退出码 0；截图路径脱敏断言通过。
- `python scripts/build_release.py --output eval/portfolio-m1-package.json`：通过，wheel SHA-256 `12220ac1ab6324e216e22cc7ff15ab5675d62b31ce0adb8f9889162a63ca52a7`，前端 15 个文件且 stale assets 为 0；报告 SHA-256 `7A8BBE6AD1149390068B641E70C1137F3F96F6ADCFA7761E9EA370D16718F033`。

### 限制与未执行

- 官方当前模型名依据 [DeepSeek 模型文档](https://api-docs.deepseek.com/quick_start/pricing/)；旧名仅保留在有历史语境的 ADR 和历史进度记录。没有改动 SemVer、冻结 gold 或旧验收 JSON。
- 未读取 API Key、未调用真实/付费 DeepSeek、未运行 Docker、未触发远程 CI，未修改或索引学习参考仓库。

### 下一步

- M2：审阅首次提交候选、暂存精确候选并运行 staged diff/密钥/文件类型检查。用户已授权“首次提交”，未授权 push；需在首次提交前由用户决定 SPDX 开源许可证，或明确选择暂不授予开源许可证。

## 2026-10-19：作品集优化 M0 基线

### 已完成

- 按 `docs/portfolio-optimization-plan.md` 建立本轮可复核基线；包版本仍为 4.1.0，路线图阶段为 V6。
- Git 根目录为 `D:/RAG/RepoLens`；当前无 `HEAD`、无 remote，基线时 225 个未跟踪路径、0 个已跟踪文件。`data/`、`dist/`、`build/`、`*.egg-info` 和 `node_modules/` 均按规则忽略。
- 环境为 Python 3.12.8、Git 2.53.0.windows.2、Node 24.16.0、npm 11.13.0；RepoLens doctor 的 Python、Git、SQLite FTS5 检查通过。

### 验证

- `$env:PYTHONPATH='src'; .\data\v5-web-venv\Scripts\python.exe -m unittest discover -s tests -v`：184 项通过，用时 154.508 秒；完整日志 `data/portfolio-baseline-tests.log`，SHA-256 `4862D2E3AAB50A77CFB411BF0538EBC98E0E8BD9E0E537E679B4A499E2F6D3AB`。退出码 0，日志末尾记录总耗时 156.889 秒（含 PowerShell 管道）。
- `python -m compileall -q src tests experiments scripts`：通过，退出码 0。
- `npm run format:check --prefix apps/web`：通过，退出码 0。
- `npm run build --prefix apps/web`：通过，退出码 0；Vite 提示最大编辑器 bundle 约 3.69 MB，作为后续性能观察项，不影响构建。
- `python scripts/export_api.py --check`：通过，退出码 0。
- `python scripts/v6_regression.py --index data/v4-flask-index --output eval/portfolio-baseline-retrieval.json`：90 次冻结检索重放通过，query error 为 0；报告 SHA-256 `E5CD6DDEF0227BBD42E2B4EC9CF565F47861F41368EF1480A3D404E21009040B`。未修改冻结 gold。
- `python scripts/build_release.py --output eval/portfolio-baseline-package.json`：通过；15 个前端静态文件，无 stale assets。wheel `repolens-4.1.0-py3-none-any.whl` SHA-256 `cc72c14e63180f8fd7e6ccaa140e3495d404f163268967b00543cd8b6e215b89`；构建报告 SHA-256 `4D1F5AE65E370A011551BCE71FCCA5958E14B6CE290D9F0ED1B95836E5128DC0`。

### 限制与未执行

- 首次 Python 命令因独立 PowerShell 未继承 `PYTHONPATH` 而失败；在每条命令显式设置后重跑通过，首次失败未计作通过。
- Docker 实机、远程 CI、真实 DeepSeek 评测未执行；未读取 API Key、未调用付费模型、未访问或修改学习参考仓库，未 commit/push。

### 下一步

- M1：统一当前 DeepSeek 模型默认名，并修正架构文档中不存在的模块映射及 webapp/workbench 主次说明；不改 SemVer、冻结评测或历史 ADR。
- M1 完成后进入 M2 首次提交候选审计；许可证仍由用户选择。

## 当前检查点：可选 LangChain 接入本地验收完成

2026-10-19：用户确认后接入 Python LangChain Core/DeepSeek adapter，决策见 ADR 0025，完整使用与验收见 `docs/langchain-integration.md`。包仍为 4.1.0；这是已授权的可选框架适配，原路线图的索引、证据、版本、只读权限与受控 Agent 边界保留。

- `RepoLensRetriever` 使用 `BaseRetriever/Document`；`answer/ask/chat` 的 CLI 与 Web 问答已接入。LCEL `ChatPromptTemplate | ChatDeepSeek.with_structured_output(json_mode)` 返回候选，RepoLens 继续负责上下文预算、schema/citation 校验和 canonical source span。
- impact 与 `ControlledAgent` 可使用 LangChain 模型适配器；Agent 没有替换成任意 LangGraph 工具执行，固定只读工具、共享预算与进程超时保留。模型、timeout、retry 等环境配置与显式覆盖规则对齐原 provider。
- 适配器显式关闭 LangSmith tracing，覆盖全局 tracing=true 的情况；错误脱敏、有限重试、截断和 SDK 解析后的 4 MiB 结构化输出检查通过。SDK 接收前没有原生 provider 的 streaming 字节截断，边界已写入 ADR。
- 最终源码全量 184 项通过，160.260 秒；最终安装包 `python -I` 专项 11 项通过；`python -S` 的 8 项 CLI 回归通过。当前包在不安装 extra 时仍能运行核心 CLI，缺少 extra 有明确提示。
- 原 V6 policy manifest 与 gold 保留；新增 `eval/v6-langchain-policy-manifest.json` 连接原始清单。实际 LangChain Retriever 重放 90 次，逐题 Recall/MRR/nDCG/条数与冻结结果一致，报告 `eval/v6-langchain-retrieval-regression.json`。
- 前端格式、TypeScript/Vite、OpenAPI、compileall 通过；最终安装包 pythonw 服务的 Playwright 8 项通过，18.119 秒，包括两种 DeepSeek 连接方式的缺 Key 提示。源码/UI/API 的 provider 枚举已同步。
- 全新 `data/v6-langchain-acceptance-venv` 安装 45 项锁定依赖，pip check 通过；干净 staging wheel 的 15 个静态文件与当前构建一致，无旧资源。最终 wheel SHA-256 为 `9ed70804f7b4ef06bc8ab5e47d46c77cfd891b55310d31bd768716975a5299ed`。独立工作台合成演示通过；汇总 `eval/v6-langchain-acceptance.json`。
- `apps/api/requirements-langchain.lock`、独立 CI job 和 Docker 可选 build arg 已提供。启动器使用的 `data/v5-web-venv` 已加装同一锁文件并通过依赖/import 检查；uv 只用于隔离环境安装，不是运行依赖。
- 当前新服务为 `http://127.0.0.1:8772/`，从最终 wheel 的 site-packages 通过 pythonw 运行，默认 Mock、未配置 Key；8771 原服务保留。未调用真实模型、未读取或保存真实 Key、未 commit/push，学习参考项目未被修改或索引。

剩余验收仍是 Docker 实机、远程 CI 与真实 DeepSeek 独立质量评测。当前适配不改变检索策略和冻结指标，也不声称回答质量因此提高。

## V6 原始工程化验收记录（LangChain 接入前）

2026-10-19：对照原始路线图第 10 节增加评测回归、安全、可观测性、部署和演示材料。详细逐项对照与偏离审计见 `docs/v6-release.md`，决策见 ADR 0024。包版本仍为 4.1.0，界面/API 阶段为 V6。

- 第一项已核对：冻结检索题集、来源和 parser/embedding/prompt/Agent 策略 hash 门禁已实现；`python scripts/v6_regression.py --index data/v4-flask-index --output eval/v6-retrieval-regression.json` 实际重放两套题、三种策略共 90 次，逐题 Recall@5/10、MRR、nDCG 和条数均与冻结记录一致。未修改 gold、策略或默认 hybrid。
- 第二项已核对：独立生成评分器覆盖正确回答、引用有效但语义错误、伪造引用、正确/错误拒答，审阅绑定 output hash；3 项测试通过。5 个 scripted fixture 结果不代表真实 DeepSeek 质量，真实语义支持度/准确率仍未测量。
- 第三项已核对：request ID、任务/Trace 日志关联、metadata-only JSON、有界 metrics/Prometheus、安全响应头、跨站拒绝、body 上限、授权根目录和历史证据限制已实现。兼容 HTTP 入口也补上跨站/非 JSON 设置限制；中途失败的 SSE 结束流且不输出异常原文。
- 第四项已核对：最终 `$env:PYTHONPATH='src'; .\data\v5-web-venv\Scripts\python.exe -m unittest discover -s tests -q` 为 170 项通过，156.437 秒。Prettier、TypeScript/Vite、OpenAPI、compileall 通过；Playwright 对最终安装包 pythonw 服务执行 8 项通过，18.9 秒，结果 `data/v6-playwright-results.json`，交付截图 `docs/screenshots/v6`，汇总 `eval/v6-acceptance.json`。
- 第五项已核对：`python scripts/build_release.py --output eval/v6-package-build.json` 在新 staging 目录构建并核对全部 15 个静态文件，无旧资源残留。新建 `data/v6-acceptance-venv` 离线安装，`python -I` 确认 site-packages 加载，doctor、核心 Demo 和 Web 演示通过；7 个任务完成，正常 Agent 5 次工具调用，预算降级 3 次，SSE、引用和导出通过。报告 `eval/v6-workbench-smoke.json` 只证明合成 Mock 契约。
- 当前 wheel SHA-256：`410ac2b30542e0646a812b26ae891ecd4d22b579ea149d4f9a294cd15f9a4c38`。旧同版本 wheel hash 仅作历史，不用于校验当前 dist。
- 第六项已核对：Docker/Compose、非 root/只读根、SQLite 卷和显式只读仓库 overlay、CI 干净构建/安装/浏览器/容器步骤与中文部署排障回滚文档已实现。但本机无 Docker，未触发远程 CI，二者没有运行验收，不能宣布 V6 全平台彻底完成。
- 偏离残留已修正：README/架构/面试/图与 Agent 使用说明和新任务交接；澄清历史 RRF 负实验与当前 hybrid 不同、包版本不等于路线图阶段、引用验证不等于语义正确。Compose 不再默认依赖 Flask；未修改/索引学习参考仓库，未迁移 Java/LangChain4j。
- 追加启动审计：修复 pythonw 缺失标准流时 Uvicorn 默认彩色日志初始化失败，加入真实 Config 的无标准流测试；新 wheel 离线重装后用 pythonw 启动，首页、health、Demo、metrics 和 8 项浏览器流程通过。固定 Flask 正常/模拟模型故障 smoke 也通过，报告 `eval/flask-agent-v6-smoke.json`；目标仍为既有 236 个 D 的 no-checkout 状态，未修改工作树。
- 当前服务：`http://127.0.0.1:8771/`，独立安装包通过 pythonw 无终端运行，默认 Mock；真实 DeepSeek Key 只通过环境/进程内存。没有真实模型调用，也没有 commit/push。下一步为 Docker 实机、远程 CI 与独立真实模型评测，不继续堆新版本掩盖验收缺口。

下方为 V5 及更早的历史验收记录；其中服务地址、包 hash 和阶段状态不代表当前结果。

## V5 收口记录

2026-10-19：按原始路线图第 9 节开始 V5。设计见 `docs/adr/0023-v5-web-workbench.md`。

- 第一项已核对：FastAPI/Pydantic 可选 API、封闭输入、只读源码/diff、单工作线程任务队列、SSE 事件补读、内存 Key、OpenAPI 和生成的 TypeScript 输入类型已实现。7 项离线 API 集成测试通过；修复了负 SSE 事件序号被默认值掩盖的问题。没有复制索引/模型/Agent 业务，没有新增目标仓库写权限。
- 第二项已核对：React/TypeScript/Vite、TanStack Query、React Router、Tailwind、Monaco、React Flow 和 Recharts 六个页面已实现；仓库导入、变更报告和 diff、关系图、检索问答、Trace、评测对比、代码证据弹窗、Markdown/JSON 导出、空/错/加载态和窄屏布局均已覆盖。diff 编辑器模型释放顺序和关系图初始聚焦问题已修复。
- 第三项已核对：`$env:PYTHONPATH='src'; .\data\v5-web-venv\Scripts\python.exe -m unittest discover -s tests -q`，152 项通过，147.283 秒（原有 145 + 7 项 V5）；`compileall`、`git diff --check`、Prettier 格式检查、TypeScript 类型检查和 Vite 生产构建通过。Playwright 8 项通过，覆盖桌面六页面、390px 窄屏、源码/证据、diff、导出、图交互、Agent Trace、评测回退样例和错误态。
- 第四项已核对：V5 wheel 已在独立 `data/v5-acceptance-venv` 中离线重装；`python -I scripts/workbench_demo.py` 返回首页 200、结构化问答 answered、12 个图节点、18 条图边、1 个变更文件、Markdown 200、Agent degraded/step_budget_exhausted 和 SSE 补读通过。wheel SHA-256 为 `e5b08fa6a868b7adf68e6736ba29e1ff4d2018fe0e0359e4f0c237cf395f991f`。
- 第五项对照原始路线图第 9 节：新用户可以打开合成 Demo 或输入自己的本地 Git 仓库路径，完成索引、分析、查看证据和导出报告；目标仓库仍只读，学习参考项目未被索引。评测页回放冻结 vector/hybrid/graph 结果及 90 条逐题召回，未把 citation schema 通过误报为 citation precision 或回答准确率；这两项仍显示未评测。
- 当前本地工作台已启动于 `http://127.0.0.1:51654/`。DeepSeek Key 仍只存在当前服务进程内存或环境变量；本轮没有真实模型调用，也没有 commit/push。V6 的 Docker、统一监控和完整生成质量评测仍未完成。

下方是 V4 及更早的历史验收记录；历史 wheel hash 不用于校验当前 V5 wheel。

## V4 收口记录

2026-10-19：V4 增加 SQLite schema 4 的持久化节点/边、增量语法缓存、当前 snapshot 重新连边、导入别名/重导出/作用域/单继承解析、一至两跳有界子图、版本检索 API，以及问答/Agent/impact 的图增强入口。

- 第一项对照：已有图 schema、构建器与缓存复用；图和源码同事务，端点通过复合外键限制在同一 snapshot。未引入新基础设施；AST 无法唯一解析的动态关系保留为 unknown，不生成全局同名猜测。replaces 类型预留，不无依据制造替代关系。
- 第二项对照：函数、文件和 commit 子图、`/api/graph`、`/api/search`、graph 检索和风险检查排序已接入。删除文件使用独立 base 子图；branch 每次固定为 SHA；`impact` 仍尊重用户选择的实际 base/head 范围。完整 UI 工作台没有提前宣布为 V4 完成项。
- 第三项对照：最终全量 `$env:PYTHONPATH = "src"; python -m unittest discover -s tests -q` 为 145 项通过，耗时 143.469 秒；其中 20 项图专项、2 项新增 HTTP API 测试，保留 V3 的 123 项回归。覆盖导入/重导出、单继承、方法裸名称与 receiver 遮蔽、歧义、跨版本/跨节点隔离、删除、分支移动、损坏数据、事务回滚、缓存重连和 Agent 节点/边预算。`compileall`、`git diff --check` 通过。
- 第四项对照：固定 Flask 10 条跨文件任务的 R@10 为 vector 0.80、hybrid 0.85、graph 0.95；R@5 为 0.60、0.6667、0.95。图策略 v2 的 nDCG@10 为 0.9226。3 题提高、1 题回退、6 题相同；同时报告额外图扩展的计算量与更高延迟。原有 20 题 graph R@10 为 0.50，低于 vector 0.5333 和 hybrid 0.6083，因此通用默认检索仍为 hybrid，图增强显式选择。
- 第五项对照：单 snapshot 的真实图包含 2,080 个节点、4,616 条边；未解析调用/导入单独统计。以第一父提交建立索引再导入 head，复用 235 个文件的语法事实，仅重新提取 1 个文件。`eval/flask-graph-v4-sample.json` 给出两跳有界图（40 节点、68 边、truncated=true），SHA-256 为 `d1a377639d46d12eedc7e051ce1a53a964a2ba15806f203d1d93eb84b3e80da9`，所有证据绑定当前 head。
- 第六项对照：最新 wheel 已用 `--no-build-isolation --no-index --no-deps` 重建，在新建 `data/v4-acceptance-venv` 中离线安装；`python -I` 确认从 site-packages 加载，doctor 通过。已安装包通过历史父提交的 `graph` 查询、`repolens.exe ask --retrieval graph --provider mock` 和进程隔离的 Agent 流程（completed/answered，5 步、21 个事件）。
- 当前产物：`dist/repolens-4.1.0-py3-none-any.whl`，SHA-256 为 `538bb09d429e96f8527a1d3c68f77bab8e4545ab57ac907efb25b11c0b4af62a`。包版本未变，安装已存在的同版本包时使用 `--force-reinstall`；下方 V3/V2 hash 是历史记录，不用于验证当前 dist 文件。
- 质量实验初跑、候选池元数据修正和作用域 v2 修正均保留独立清单与结果；没有覆盖 gold 或依据结果调整排序权重。当前实现 hash 与最终 v2 清单逐文件匹配。详见 `docs/evaluation-graph-v4.md`。
- 最终审计：42 个本轮源码、文档与生成产物通过额外 whitespace 检查（含未跟踪文件，保留 JSON 原始 CRLF 字节）；`compileall` 与 `git diff --check` 通过。Git 候选文件中没有数据库、环境文件或密钥；源码未发现长 API-key 形式。Flask 目标仍是既有 no-checkout 布局的 236 个 D 状态，无其他条目；未恢复或修改目标工作树。当前 wheel hash 与交接记录一致，所有必要命令已退出。

按原始路线图第 8.3/8.4 节逐项核对：schema、构建与增量、子图 API、版本检索 API、节点/边/证据格式、图增强对比均已交付；函数/commit 的关系查询、历史隔离、跨文件量化收益与来源校验均有对应证据。限制明确：Python 静态图、动态分派/复杂多继承/外部库不保证覆盖；replaces 没有可信来源时只保留类型；文档关系缺少显式提及时不编造。通用默认 hybrid，完整关系图工作台和部署分别属于 V5/V6。本轮未使用真实模型或 API Key，未修改/运行目标仓库代码，未索引学习参考项目，未 commit/push。

设计、使用、评测说明：`docs/adr/0022-versioned-static-code-graph.md`、`docs/v4-graph.md`、`docs/evaluation-graph-v4.md`。下方 V1/V2/V3 和旧包版本记录描述当时状态，当前阶段以本检查点为准。

## V3 收口记录

2026-10-19：继续按原始路线图 V3 实施，V1/V2 验收结论保留。

- 第一项：八个固定只读工具与严格参数、固定 root/base/head snapshot、引用 source-span 校验已实现。对照检查：没有 shell、写文件、网络抓取和版本切换权限；一跳 AST 候选明确标记 inference，不冒充 V4 代码图谱。
- 第二项：显式状态机、工具/模型共享预算、可终止 spawn 工作进程、重复调用抑制、连续错误停止和 V2 规则报告降级已实现。18 项 Agent 专项测试通过，包含越权、未来版本隔离、非法规划、伪造引用、token/step/result/model-call 限制、模型阻塞超时与进程回收。
- 第三项：`agent` CLI 与 `/api/agent` 已接入；task/trace ID、工具参数、结果定位、模型输出 hash、耗时和分类错误均进入响应中的 Trace。完整 Web 工作台仍按 V5 实施。
- 第四项：全量 `$env:PYTHONPATH = "src"; python -m unittest discover -s tests -q` 为 123 项通过，耗时 93.156 秒；包含 HTTP API 和 2 项 DeepSeek JSON 规划协议/序列化测试。`python -m compileall -q src tests experiments scripts`、`git diff --check` 与新建未跟踪文件的额外 whitespace 检查通过。
- 第五项：固定 Flask commit `d086db856be187255b8ec61ef409357393020f32` 及第一父提交的离线 smoke 通过。Mock 正常场景 completed/answered，6 步、25 个事件、15 条保留证据；模拟 provider 故障场景 degraded/abstained，2 步、11 个事件、9 条保留证据。两者保留 V2 规则报告，样例见 `eval/flask-agent-v3-smoke.json`，SHA-256 为 `6440e99bfb2ad7e6a1a272a2e7f3055dbea3409a59883487e3721b75fb69db02`。
- 第六项：`python -m pip wheel . --no-deps --no-build-isolation --no-index --disable-pip-version-check --wheel-dir dist` 离线构建通过；当前 `dist/repolens-4.1.0-py3-none-any.whl` 的 SHA-256 为 `d7fc32f50c7edb3d4f2af97d742b6b7691442bc42e87e8b538c07621407497dd`。新建 `data/v3-acceptance-venv` 并离线安装；`python -I` 确认从该环境 site-packages 加载；doctor 通过；已安装包 `python -I -m repolens agent ... --provider mock` 在相同 Flask commit 上返回 completed/answered、6 步、25 个事件并保留规则报告。
- 最终审计：直接执行安装环境的 `repolens.exe agent ... --max-steps 3` 也通过，预算结束后返回 degraded/step_budget_exhausted，仍在剩余预算内生成经过引用校验的 answered。21 个改动文件通过额外 whitespace 检查（保留 JSON 的原始 CRLF 字节）；当前 wheel hash 与记录一致；Git 候选文件没有数据库、`.env` 或密钥文件。Flask 仍为既有 no-checkout 布局的 236 个 D 状态，无其他条目，未恢复或修改该目录。

逐项对照原始路线图第 7 节：工具白名单、task/trace 关联、可解释失败和有界重试、固定离线配置复现、Agent 不可用时保留基础能力均已有对应验证，V3 按上述边界交付。没有调用真实 DeepSeek API，未使用真实 API Key；不声称真实模型的 Agent 任务成功率、结论支持度或成本已经评测。V4 持久化代码图谱、V5 完整工作台、V6 工程化仍未完成。本轮没有执行、安装或修改目标仓库代码，没有使用学习参考仓库，没有 commit 或 push。

设计、使用和验收说明：`docs/adr/0021-controlled-agent-budget-and-trace.md`、`docs/v3-agent.md`、`docs/evaluation-agent-v3.md`。Trace 不自动持久化，不记录源码或未经校验的模型原文。远程模型配置可重复，不承诺远程生成逐字一致；离线 Mock 不代表真实模型质量。下方 V2/旧包版本记录仅描述当时状态，当前阶段以本检查点为准。

## V2 收口记录

本轮开始修正历史版本职责错位。V4.1.0 的代码和 Web UI 保留，但路线图阶段不再用“包版本号已经增加”代替能力验收。当前完成的 V1 对齐内容如下：

- 新增 `EmbeddingProvider` 契约和标准库实现的 `local-tfidf-v1` 稀疏向量基线；该实现用于离线、可复现检索，不宣称是通用语义 embedding。
- SQLite schema 升为 2，每个 snapshot 保存独立 vector model 和 chunk vectors；旧 schema 在下一次可写 ingest 时自动创建向量表并回填。
- 新增 `IndexStore.search_vector` 和加权 RRF `search_hybrid`，CLI `search` 支持 `keyword/vector/hybrid`，`ask/chat` 默认使用 hybrid，可显式指定路径。
- 新 commit 在父 snapshot 可用时按 blob、路径和语言复用未变化文件的解析结果；新增/修改文件重新解析，并在 stats 中记录 `index_mode`、`base_snapshot_id`、`reused_files`、`parsed_files`。
- 新增 bounded Git history：每个 snapshot 最多保存 5,000 条可达 commit，独立支持 `history` CLI 和 `search_history`，不把提交记录混入代码 evidence。
- snapshot stats 记录包含当前 commit 的本地 branch 名称；commit SHA 仍是唯一版本边界。
- V2 impact hardening 已完成：报告 schema 升为 `repolens.impact.v2`，增加历史/配置分组、有限 Python AST callers/callees、low/medium/high/blocking 风险等级、Markdown renderer、`analyze commit` 入口、evidence 完整性校验和 10 个真实 Flask commit 样例；结构化评测见 `docs/evaluation-impact-v2.md`。动态调用和跨语言图谱仍是明确边界，不属于当前 V2 交付范围。
- 新增 ADR `docs/adr/0017-roadmap-alignment-v1-vector-retrieval.md`，明确 TF-IDF 基线、snapshot 隔离、迁移和后续外部 provider 的边界。

本轮验证：`$env:PYTHONPATH = "src"; python -m unittest discover -s tests -q`，102 项通过；`python -m compileall -q src tests experiments scripts` 通过；`git diff --check` 通过；真实 Flask 固定 commit 完成 keyword/vector/hybrid 三路评测，结果见 `docs/evaluation-v1.4.md`；schema 2 → 3 迁移、history CLI 和 local branch metadata 通过；impact 专项、`analyze commit`、有限 Python AST callers/callees、10 个真实 commit 样例和 `evaluate-impact` 结构化评测通过。V2 wheel 已重建并完成离线安装验收。V3 白名单 Agent、V4 代码图谱、V5 完整工作台和 V6 工程化评测仍未完成。

本轮完成 V4.0 本地浏览器应用改造。用户可以双击 `RepoLens.pyw`，自动打开本地 Web UI；页面提供代码问答、连续对话和两 commit 影响分析。后端复用既有 pipeline，只绑定 loopback；API Key 设置只存在服务进程内存。V3.2 的追加检索和 V3.3 的 impact 能力继续保留。默认 provider 仍按命令区分：`answer` 使用 Mock，`ask/chat` 使用 DeepSeek，`impact` 和 Web UI 默认使用 Mock；API key 只从进程环境或当前 UI 进程设置读取，不进入源码、日志、错误信息或 Git。
本轮在 V4.0 本地浏览器应用之上完成 V4.1 多语言检索增强。用户可以直接用中文询问常见代码问题；固定词典会把“入口、读取、写入、书籍”等扩展为有限英文/代码提示，同时保留显式 identifier。后端不调用模型做 query 翻译，不联网，不改变证据和 citation 边界。

### 历史已实现的生成与 Web 能力

- `repolens.provider`：vendor-neutral `ProviderRequest` / `ProviderResponse` / `Provider`，以及不联网的 `MockProvider`。
- `repolens.context`：按 UTF-8 字节估算 token，保留完整 evidence、不截断源码、去重并报告被预算淘汰的 evidence。
- `repolens.answer`：严格的 `repolens.answer.v1` JSON schema；每个 answered claim 必须引用已打包的 `E1` 等 citation ID。
- `repolens.pipeline`：`retrieve -> pack -> provider -> validate` 闭环；没有证据或预算无法容纳证据时，在 provider 调用前直接 abstain。
- `DeepSeekProvider`：读取 `DEEPSEEK_API_KEY`，默认请求 `https://api.deepseek.com/chat/completions`，默认模型 `deepseek-v4-flash`，使用 JSON mode 输出结构化候选。
- CLI `answer` 支持 `--provider mock|deepseek`，以及 `--model`、`--timeout`、`--max-retries`。
- provider 返回未知 citation、无引用 claim 或不符合结构的 JSON 时 fail closed，不把模型文本当作事实。
- V2.2.0 hardening：CLI 参数 typed range validation；provider context/output/response 上限；回答 claims/citations/unknowns 上限；DeepSeek request id、usage、attempts、耗时 telemetry；错误不暴露服务端原文或 key。
- V2.3.0：新增 `ask <question> --repository <path>`，默认 `HEAD`、默认 DeepSeek、默认输出 1024 token；结果包含 `workflow` 元数据，记录仓库、commit、snapshot 和索引统计。
- V2.4.0：相同仓库、commit 和 index policy 命中已有 snapshot 时直接复用；`workflow.index_action` 为 `created` 或 `reused`。
- V3.1.0：新增 `chat` 交互命令、最近 8 条对话历史、`:help`/`:quit`、每轮当前 evidence citation 约束和最大 20 轮默认限制。
- V3.2.0：新增 `--max-follow-ups 0..3`；`ask/chat` 默认 1 次追加检索，记录 retrieval/generation rounds、追加次数和全部 retrieval queries；每轮仍使用同一 snapshot 和 citation validator。
- V3.3.0：新增 `impact --repository <path> --base <ref> --head <ref>`；Git 层读取 bounded diff/hunks，索引层提供 path/symbol/chunk 查询，报告包含 changed files、changed symbols、related tests/docs、规则风险、建议测试、unknowns 和可选一次 `model_answer`。
- V4.0.0：新增 `repolens.webapp`、`repolens-ui`、`repolens serve` 和根目录 `RepoLens.pyw`；页面复用 ask/chat/impact 逻辑，提供 loopback JSON API、内存 API Key 设置和本地工作区记忆。
- V4.0.1：修复 Windows Git dubious ownership；仅为用户明确选择的仓库注入命令级 `safe.directory`，不修改全局 Git 配置。
- V4.0.2：检索层排除只包含空白字符的 evidence chunk，避免旧索引中的空 module chunk 破坏上下文打包。
- V4.0.3：修复 SQLite 对换行字符的空白判断；实际验证 `Book Manager V1` 的 `ask` 和浏览器问答均返回 `answered`。
- V4.1.0：新增 bounded multilingual query expansion；纯中文 fixture 和 `Book Manager V1` 真实中文问题均能召回 `main.py`、`book_manager/book_io.py` 等 evidence。
- 历史 V2 wheel SHA-256 为 `683eaa3fe5e55ac4799b9dcc47ad88ec81f37673090755fda957b68e7eecb70a`；当时安装到 `data/v2-acceptance-venv` 并验证。当前 dist 同版本文件已由上方 V3 wheel 替换，不再使用此历史 hash 校验现有产物。

路线图 V1 和 V2 已完成验收。V1 完成本地索引、keyword/vector/hybrid 检索、证据校验、真实三路评测、bounded history、分支元数据、安装包和演示闭环；V2 完成结构化 impact、有限静态 callers/callees、JSON/Markdown、`analyze commit`、evidence 完整性和 `evaluate-impact`。项目未创建 Git commit，也未发布到外部服务。

### 已交付

- CLI：`doctor / ingest / snapshots / search / answer / evidence / evaluate`。
- Git commit objects 只读索引，Python AST 与 Markdown 分块，SQLite 事务及 FTS5 检索。
- 固定 100 候选的词法重排；改变 `--limit` 时保持排名前缀一致。
- 同名 getter/setter、overload 依据具体包含范围验证；拒绝损坏索引中的空、逆序、越界证据。
- 包版本由 `src/repolens/__init__.py` 单一维护，wheel 为 `dist/repolens-1.0.0-py3-none-any.whl`。
- `scripts/demo.py` 在临时 Taskboard 仓库完成已安装包的端到端演示。
- GitHub Actions 已配置 Windows/Ubuntu、Python 3.12/3.13；未触发远程 CI。
- 中文验收记录：`docs/v1-release.md`；面试说明：`docs/interview-guide.md`。

### 评测

Flask 固定 commit：`d086db856be187255b8ec61ef409357393020f32`。

Snapshot：`snapshot_d157332a493291d8065f3d78825454f7479f8f6c8cbc9ea5bcb25f818a756656`。

新验收索引：`data/v1-flask-index`；236 个 tree 条目、89 个源码文件、1,622 个符号、2,256 个 chunks。

| 数据集 | 题数 | R@5 | R@10 | MRR@10 | 去重 nDCG@10 |
|---|---:|---:|---:|---:|---:|
| 原开发集，参与调参 | 30 | 0.708 | 0.792 | 0.858 | 0.732 |
| 新冻结验证集 | 20 | 0.550 | 0.650 | 0.550 | 0.554 |

新验证集为 `eval/flask-validation.jsonl`，28 条 locator，四类各 5 题。其 SHA-256 为 `2950d7b188a3ebaf58fc1623c465ce5edd1e5a8b5cb6f11aac760f45eec7f6fc`，冻结清单为 `eval/flask-validation-manifest.json`。在首次检索前记录题集与检索实现 hash，之后没有调权重或改标注。它仍是同仓库验证，不是外部盲评。

纯中文无代码标识符的 5 题全部无命中；英文自然语言 R@10 0.6，精确标识符和带标识符多方法类别均为 1.0。V1 的跨语言语义检索能力不足，不能以其他类别分数掩盖这一点。

### 验证与运行

本机 Python 3.12.8、Git 2.53.0.windows.2、SQLite 3.45.3/FTS5。

- `$env:PYTHONPATH = "src"; python -m unittest discover -s tests -v`：56 项通过。
- `python -m compileall -q src tests experiments scripts`：通过。
- wheel 使用 setuptools 81.0.0 离线构建，在 `data/v1-acceptance-venv` 离线安装；`python -I` 确认从 site-packages 导入，版本为 1.0.0。
- `.\data\v1-acceptance-venv\Scripts\python.exe -I scripts/demo.py`：通过，输出见 `eval/v1-demo.json`。
- 已安装包重建 Flask 新索引并完成两套数据评测，结果为 `eval/flask-v1-ingestion.json`、`eval/flask-v1-development.json`、`eval/flask-v1-validation.json`。
- 验收包及文件摘要见 `eval/v1-acceptance.json`。
- Flask 仓库只读。索引时沙箱账户触发 Git ownership 检查，已获执行批准后以仓库所属用户读取，没有放宽全局 Git 配置。

### V2 验证

- `$env:PYTHONPATH = "src"; python -m unittest discover -s tests -v`：83 项通过。
- `python -m compileall -q src tests`：通过。
- 固定 Flask snapshot 上运行 `python -m repolens answer ... --context-tokens 1200`：返回 `answered`，上下文使用 868 token，canonical citation 为 `E1`，包含 snapshot/commit/path/symbol/行号。
- 空检索和预算不足测试确认 provider 调用次数为 0；未知 citation、无引用 claim 和非法结构均 fail closed。
- DeepSeek provider 离线 HTTP 测试覆盖 JSON mode、请求体、解析、401 不重试、临时网络错误重试、缺少 key 和非法 JSON；测试未联网、未读取真实 key。
- V2.2.0 新增离线测试覆盖响应体大小上限、request id/attempts/latency、provider 输出预算、回答输出数量上限和 CLI 参数错误。
- 真实 DeepSeek smoke test：`provider=deepseek`，`status=answered`，`context.tokens_used=956`，`token_budget=1200`，`citations=E1..E4`，1 条低优先级 evidence 因预算被淘汰；未记录或提交 key。
- `ask` 离线集成测试：临时 Git 仓库执行 `ask -> ingest -> answer`，确认 workflow snapshot、commit、telemetry 与回答一致。
- snapshot 复用测试：同一临时仓库连续两次 `ask`，第一次为 `created`，第二次为 `reused`，snapshot ID 一致。
- chat 离线集成测试：临时 Git 仓库启动 `chat`，完成一轮问题并使用 `:quit` 退出。

### 历史记录

V1.2 未调参基线与 V1.3 开发集结果分别保留在 `eval/flask-baseline.json` 和 `eval/flask-v1.3-baseline.json`。原题集 SHA-256 为 `77cfaea4a405c21716583ad9498715b28ab0b6b2278924eca843b3715503cd37`，未改动。

V1.3 审阅：R@10 有 6 题改善、3 题回退。独立的字面标识符子查询/RRF 实验 R@10 为 0.753，新增两道零命中题，未启用为默认。报告和原始 hash 保留在 `docs/evaluation-review-v1.3.md` 与 `eval/flask-v1.3-review.json`；历史实现 hash 描述当时的文件，不要求与此后的修复文件相同。

### V4 验收

当前确定性回归测试共 93 项，覆盖 V3.2 追加检索、V3.3 impact、V4 Web API 以及 V4.1 中文 query expansion。源码 Web UI 已用浏览器验证纯中文问题返回 `answered` 并引用 `book_manager/book_io.py`；`compileall` 与 `git diff --check` 已通过。V4.1 wheel 离线安装后继续验证 `doctor`、版本、CLI 帮助和真实 `Book Manager V1` 中文问答；不把这组 fixture 结果称为跨仓库语义检索质量。

路线图 V1 只支持 Python/Markdown 的 committed blobs，其他语言另行实现；V2 已完成 DeepSeek provider、离线结构化回答核心、ask/chat、impact v2、有限 Python AST caller/callee、`analyze commit`、10 个真实 commit 样例和结构化质量评测。V2 的调用关系边界是静态 Python AST，不覆盖动态调用、反射或跨语言关系；质量 gold 是结构化契约评测，不代表生产风险召回。V3 的受控 Agent、V4 的代码图谱、V5 的完整工作台和 V6 工程化仍未完成。V4.1 的中文能力仍是有限词典扩展，不是通用语义检索。学习参考仓库 `all-in-rag`、`AgentGuide` 始终不是目标仓库。

## 新任务起始语

读取 `D:\RAG\RepoLens\AGENTS.md`、本文件与 `docs/langchain-integration.md`，核对 Git 状态后继续。V1-V6 原有本地验收保留；用户授权的可选 LangChain Core/DeepSeek adapter 已完成，最终 184 项 Python、11 项安装包专项、8 项浏览器与实际 Retriever 的 90 次重放通过。当前服务 8772、双击环境依赖已准备。Docker 实机、远程 CI 和真实 DeepSeek 质量仍未测。SQLite schema 4、图策略 python-import-scope-graph-v2、默认 hybrid 和 gold 不变；Agent 仍为 RepoLens ControlledAgent。包4.1.0，当前 wheel hash 以顶部检查点为准。不把 fixture 当模型质量，不启动未授权的重写。参考项目 all-in-rag/AgentGuide 不修改、不索引、不评测；未授权 commit/push 或 subagent。
