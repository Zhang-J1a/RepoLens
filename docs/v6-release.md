# V6 本地工程化交付与验收边界

日期：2026-10-19。对照原始路线图第 10 节实施，包版本仍为 4.1.0。

当前状态（2026-10-20 更新）：V6 本地实现、跨平台远程 CI 及 CI 容器验收已通过。[运行 39273995176](https://github.com/Zhang-J1a/RepoLens/actions/runs/39273995176) 对应提交 `39e2859bde3b04188cf6fadc9f5e4bf69867b01b`，六个 job 全绿，包含 Windows/Linux Python 3.12/3.13、LangChain、Web/浏览器、Docker build/start/Demo 和只读挂载。宿主机仍未安装 Docker，不声称本机容器验收。真实 DeepSeek 生成/Agent 质量尚无独立标注评测。

后续用户授权的可选 LangChain 接入也已完成本地验收：184 项 Python、11 项最终安装包专项、8 项浏览器、实际 Retriever 的 90 次冻结重放通过。当前 wheel 与 8772 服务以 [LangChain 接入记录](langchain-integration.md) 和 `eval/v6-langchain-acceptance.json` 为准；下方的 170 项/410ac2... hash/8771 地址保留为本次适配前的 V6 原始验收记录。

## 逐项对照

| 原始要求 | 实现与证据 | 当前状态 |
|---|---|---|
| 离线检索评测与回归 | 冻结题集、策略实现 hash、逐题 Recall/MRR/nDCG/条数，`eval/v6-retrieval-regression.json` | 90 次查询实际重放通过 |
| 引用与生成独立评测 | `generation_evaluation.py` 与保存回答/独立审阅标签，审阅绑定确切输出 hash | 评分器 3 项测试通过；5 个反例回放，真实模型未测 |
| Agent 与端到端 | 独立安装包的 Mock 正常与预算降级、工具成功率、重复调用、Trace 完整性、任务耗时 | `eval/v6-workbench-smoke.json` 通过，属于契约演示 |
| 可观测性 | request ID、后台任务上下文、task/trace 关联、JSON 日志、JSON/Prometheus metrics | API、日志脱敏、有界指标测试通过 |
| 安全限制 | Host/Origin、JSON/128 KiB、CSP、目录授权、历史证据限制、只读 Git、Agent 工具权限 | 既有安全测试与新增 V6 测试通过 |
| 密钥管理 | 环境变量或服务进程内存，不回显、不进入日志/导出/Git | 离线设置与错误路径测试通过 |
| 容器化 | 多阶段前端构建、非 root、只读根、数据卷、显式仓库只读挂载 | CI 实跑 build/start/Demo、挂载导入和 `RW=false` 通过；本机无 Docker |
| CI | Windows/Linux 核心；Web 格式/类型/构建/API/浏览器/安装包；Docker 干净启动和挂载检查 | 已公开推送并通过六个 job，固定运行链接见本文件顶部 |
| 部署、排障、重建和回滚 | `deployment.md`、`threat-model.md`、`observability.md`、ADR 0024 | 已提供 |
| 演示材料 | 六页面演示脚本、桌面/390px 截图、独立安装包演示 | 已实际生成与查看 |

## 偏离与残留审计

| 发现 | 处理 |
|---|---|
| 包版本号与路线图阶段混用 | 保留包 4.1.0，界面/API 标记 V6；当前验收由本文件和 progress 决定 |
| 旧文档仍称 Web/Trace/图页面待开发 | 更新当前架构、使用说明、README 和交接语；旧 ADR/实验作为有日期的历史保留 |
| 面试说明把早期失败的子查询 RRF 实验与当前 hybrid 混为一谈 | 明确两项实验不同，当前 hybrid 仍使用 keyword/vector RRF |
| 早期 keyword 分数容易被当作当前检索/生成质量 | 当前优先报告 V4 三路同条件结果，真实生成字段保持未评测 |
| Compose 曾默认绑定特定评测仓库 | 基础配置仅使用自带 Demo；自己的仓库必须显式启用 overlay，只读挂载 |
| 新目录限制可能被旧 snapshot 证据绕过 | 同时检查工作区列表、任务、源码与 diff 的历史 snapshot |
| 兼容 HTTP 入口缺少跨站设置限制 | 增加 Host/Origin/Sec-Fetch-Site 与 JSON POST 检查，并验证 Key 未被修改 |
| 标准流为 None 的 pythonw 启动路径 | launcher 不写缺失的 stdout，关闭依赖控制台的 Uvicorn 默认彩色日志配置；增加无标准流回归，并用真实 pythonw 启动已安装包 |
| 重复构建可能留下旧前端 chunks | `build_release.py` 使用全新 staging 目录，逐文件 hash 比对 wheel 与当前前端 |
| 引用定位有效可能被误称为语义正确 | 独立评分器加入“有效引用但结论错误”反例，不以 schema 通过推断质量 |

产品继续接受用户授权的通用本地 Git 仓库，当前结构化解析以 Python/Markdown 为主。未引入 Java/LangChain4j 迁移；学习参考项目没有被修改、索引或用于评测。

## 实际验证

```powershell
cd D:\RAG\RepoLens
$env:PYTHONPATH = "src"
.\data\v5-web-venv\Scripts\python.exe -m unittest discover -s tests -q
.\data\v5-web-venv\Scripts\python.exe scripts/export_api.py --check
.\data\v5-web-venv\Scripts\python.exe scripts/v6_regression.py --index data/v4-flask-index --output data/v6-retrieval-recheck.json
python -m compileall -q src tests experiments scripts
```

最终 Python 170 项通过，156.437 秒，包括原 V5 的 152 项和新增 18 项。Playwright 对已安装包的 pythonw 服务执行 8 项，全部通过，18.9 秒；前端 Prettier、TypeScript、Vite 构建与 OpenAPI 检查通过。完整命令输出保存在本地 `data/v6-tests.log`、`data/v6-playwright-results.json`，汇总和产物 hash 见 `eval/v6-acceptance.json`；源码回归未替代安装包验收。

```powershell
npm run format:check --prefix apps/web
npm run build --prefix apps/web
python scripts/build_release.py --output eval/v6-package-build.json
python -m venv data/v6-acceptance-venv
.\data\v6-acceptance-venv\Scripts\python.exe -m pip install --no-index --find-links data/v5-wheelhouse -r apps/api/requirements-web.lock
.\data\v6-acceptance-venv\Scripts\python.exe -m pip install --no-index --no-deps --force-reinstall dist/repolens-4.1.0-py3-none-any.whl
.\data\v6-acceptance-venv\Scripts\python.exe -I -m repolens doctor
.\data\v6-acceptance-venv\Scripts\python.exe -I scripts/workbench_demo.py --output data/v6-workbench-recheck.json
```

该次 V6 原始 wheel SHA-256：`410ac2b30542e0646a812b26ae891ecd4d22b579ea149d4f9a294cd15f9a4c38`。15 个前端文件与 wheel 逐一匹配，旧资源数为 0。它与 V5/V4 等旧 hash 均只用于历史记录。

已安装包从新环境 site-packages 加载，首页 200、Mock answered、12 节点/18 边、1 个变更文件、真实不同的 base/head 文本、Markdown 导出 200、SSE 补读、request ID 和 metrics 均通过。7 个任务全部完成，正常 Agent 5 次工具调用全部成功，预算降级场景 3 次全部成功，两者重复调用为 0、Trace 关联完整。

该次合成流程总耗时 10,484 ms；7 个不同类型任务的执行耗时 P50=719 ms、P95=3,881.5 ms，仅描述这次混合演示样本，包含索引、问答和 Agent，不能当作稳定负载性能或真实模型延迟。Mock 没有真实计费 token/成本，字段保持 null。

真实 `pythonw.exe -m repolens.workbench.launcher --port 8771 --no-browser` 已从独立安装环境启动，首页/health/Demo/metrics 均通过；浏览器 8 项流程也对该无终端进程完成验证。当前地址为 `http://127.0.0.1:8771/`。这补充验证了用户实际需要的无终端运行方式；没有使用终端重定向来绕过缺失标准流。

固定 Flask commit 上另跑正常 Mock 与模拟 provider 故障，分别 completed/answered 和 degraded/abstained，均保留规则报告和证据。见 `eval/flask-agent-v6-smoke.json`，SHA-256 为 `e3e32bcc08fe310253aa807f60080b8e9c1c8bd93c37fcc4764e3f0ef2458623`；这是实际代码仓库上的离线契约 smoke，不是真实模型质量。

## 生成质量的使用方式

```powershell
python scripts/evaluate_generation.py `
  --responses eval/v6-generation-responses.json `
  --judgments eval/v6-generation-judgments.json `
  --output data/v6-generation-recheck.json
```

这 5 例是人为构造的评分器反例：正确回答、有效引用但错误结论、伪造引用、正确拒答、错误拒答。得到结构化通过率 0.8、正确率 0.4、有效输出的引用支持度 0.5；这些数字刻意验证评分器能区分概念，不能作为 DeepSeek 表现。

真实质量评测需要固定问题、commit、model、prompt、实际响应与 usage，再由独立审阅给出 answerability、correctness 和每个 claim/citation 的支持度标签。输出改变后必须重新审阅，不能沿用旧输出 hash。无标注、无实测 token 或无价格来源时不生成准确率/成本数字。

## 五分钟演示

1. 双击 `RepoLens.pyw`，点击“打开演示仓库”。当前电脑环境目录和后备批处理沿用 V5 命名，执行当前 V6 源码。
2. 变更分析输入 Base=`HEAD~1`、Head=`HEAD`，查看 diff、变化符号、证据与 Markdown 导出。
3. 图起点输入 `TaskService.create_task`，展开两跳，点击节点/边查看来源。
4. 问答输入 `TaskService.create_task 如何处理任务标题？`，打开引用；Mock 只演示流程，真实问答在设置中选择 DeepSeek。
5. Trace 将最大步数设为 3，展示降级原因和已保留结果；再运行默认预算展示正常完成。
6. 评测页比较跨文件收益与通用题回退；打开 `/api/metrics` 和 `/metrics`，用 task 的 request ID 对照结构化日志。

截图见 [仓库页面](screenshots/v6/workspace-desktop.png)、[变更分析](screenshots/v6/analysis-desktop.png)、[Trace](screenshots/v6/trace-desktop.png)、[390px 关系图](screenshots/v6/graph-mobile.png)。自动演示使用 `scripts/workbench_demo.py`，无需 API Key，不执行目标仓库代码。

## 尚未完成的验收

1. 在有 Docker 的干净环境实际构建并运行 Compose，执行 `scripts/container_smoke.py`；检查可选仓库只读挂载。当前无 Docker CLI/安装目录，不将配置审查当作容器运行证明。
2. 用户发布到 Git 后运行 GitHub Actions，取得 Linux/Windows 与容器的真实结果；本轮没有 commit/push 授权，不会主动发布。
3. 使用真实 DeepSeek 保存一批固定问题响应，并进行独立人工标注。现有核心回归与评分器不替代该项。

仍不承诺多租户、公开部署、通用语义/跨语言 embedding、TypeScript/Java 结构化解析、动态调用图、任意代码沙箱或持久化任务恢复。锁定的 Starlette TestClient 对 httpx 有弃用提示，当前测试通过；更换依赖时需要重跑 API 与浏览器回归。
