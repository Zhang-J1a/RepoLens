# LangChain 接入与本地验收

日期：2026-10-19。状态：可选 LangChain 接入完成，本地验收通过；包版本仍为 4.1.0。决策见 [ADR 0025](adr/0025-optional-langchain-adapter.md)。

## 直接使用

本机双击 `D:\RAG\RepoLens\RepoLens.pyw`。启动器使用的 `data/v5-web-venv` 已安装并检查可选依赖；该目录名是历史名称，实际运行当前源码。

1. 点击“打开演示仓库”，或导入自己已存在的本地 Git 仓库。
2. 打开“模型设置”，回答模型选择 `LangChain + DeepSeek`，填入自己的 DeepSeek API Key 并保存。
3. 在“检索与问答”输入 `TaskService.create_task 如何处理任务标题？`（自带 Demo），查看回答和引用。

当前最终安装包的无终端服务也已运行于 `http://127.0.0.1:8772/`，使用 `data/v6-langchain-acceptance-venv`，默认 Mock、未配置 Key。原来的 8771 服务仍是历史 V6 包，不用于这次 LangChain 验收。Key 只进入服务进程内存，重启后需重新配置。

设置界面的实际截图见 [LangChain 模型设置](screenshots/v6/langchain-settings.png)。

CLI 的 `answer / ask / chat / impact / agent` 可选 `--provider langchain`。`answer/ask/chat` 会同时使用 LangChain Retriever 与模型链；impact 和受控 Agent 使用 LangChain 模型适配器，保留各自原来的工具/规则流程。

## 实际采用的框架

| 层 | 当前实现 |
|---|---|
| Git、解析、索引 | RepoLens 读取 commit objects，Python AST/Markdown，SQLite/FTS5/本地 TF-IDF/静态图 |
| Retriever | LangChain Core `BaseRetriever`，把固定 snapshot 的证据转换成 `Document` 和来源 metadata |
| 模型链 | LCEL `ChatPromptTemplate \| ChatDeepSeek.with_structured_output(..., method="json_mode")` |
| 验证 | RepoLens 上下文预算、answer schema、当前 citation ID 与 canonical source-span 校验 |
| Agent | RepoLens `ControlledAgent`，固定只读工具、显式状态机、共享预算和 spawn 超时 |
| Trace | RepoLens metadata-only Trace；适配器显式关闭 LangSmith tracing |

当前依赖基线是 LangChain Core 1.6.12、`langchain-deepseek` 1.1.1、LangSmith 0.14.11。没有安装未使用的 `langchain` 聚合包或 LangGraph Agent；LCEL 和 Retriever 本身属于 LangChain Core。原生 `deepseek` provider 与标准库核心继续可用。

检索模型、词典、排名、默认 hybrid 和冻结 gold 都没有调参。接入框架不构成回答准确率或检索质量提升的证据。

## 安装与配置

完整 Web + LangChain 依赖共 45 个包，精确版本在 `apps/api/requirements-langchain.lock`。新环境可先安装该锁文件，再安装 wheel：

```powershell
python -m pip install -r apps/api/requirements-langchain.lock
python -m pip install --no-index --no-deps dist/repolens-4.1.0-py3-none-any.whl
```

源码开发可用 `pip install -e ".[langchain]"`。本机安装时旧 pip 的候选解析异常缓慢，实际用隔离环境中的 uv 0.13.1 安装锁文件；uv 只作为安装工具，不属于应用依赖。

模型配置沿用 `DEEPSEEK_API_KEY / DEEPSEEK_MODEL / DEEPSEEK_BASE_URL / DEEPSEEK_TIMEOUT_SECONDS / DEEPSEEK_MAX_RETRIES`；CLI 显式参数优先。LangChain 默认 base URL 规范化为 `https://api.deepseek.com/v1`。

Docker 默认仍只装 Web。可选 LangChain 镜像使用 `docker compose build --build-arg REPOLENS_LANGCHAIN=1`。本机没有执行 Docker 构建；CI 新增独立可选集成 job，但没有推送或运行远程 CI。

## 实际验收

| 项目 | 本轮结果 |
|---|---|
| 完整 Python 离线回归 | 184 项通过，160.260 秒，无跳过 |
| 最终安装包专项 | `python -I` 从 site-packages 执行 11 项 LangChain 测试通过 |
| 无第三方包 CLI | `python -S` 执行 8 项 CLI 测试通过 |
| 冻结检索回放 | 实际 LangChain Retriever 路径 90 次，逐题 Recall/MRR/nDCG/条数一致 |
| 浏览器 | 最终安装包 pythonw 服务 8 项通过，18.119 秒，包含两种 DeepSeek 连接方式缺 Key 提示 |
| 前端与契约 | Prettier、TypeScript/Vite、OpenAPI 检查、compileall 通过 |
| 安装与打包 | 干净 staging 构建；45 项锁定依赖全新安装且 pip check 通过；15 个静态文件，无旧资源 |
| 工作台合成演示 | 问答/引用、图、diff、导出、SSE、正常与预算降级 Agent 通过 |

主要复现命令：

```powershell
$env:PYTHONPATH = "src"
.\data\v6-langchain-venv\Scripts\python.exe -m unittest discover -s tests -q
.\data\v6-langchain-venv\Scripts\python.exe scripts/v6_regression.py --index data/v4-flask-index --langchain-retriever --output eval/v6-langchain-retrieval-regression.json
.\data\v6-langchain-acceptance-venv\Scripts\python.exe -I -m unittest discover -s tests -p test_langchain_integration.py -q
.\data\v6-langchain-acceptance-venv\Scripts\python.exe -I scripts/workbench_demo.py --output eval/v6-langchain-workbench-smoke.json
```

最终 wheel SHA-256：`9ed70804f7b4ef06bc8ab5e47d46c77cfd891b55310d31bd768716975a5299ed`。汇总见 `eval/v6-langchain-acceptance.json`，构建明细见 `eval/v6-langchain-package-build.json`；原 V6 的清单和评测结果仍保留。

专项覆盖真实库链构造和 JSON parser、环境配置与覆盖、provenance、跨 snapshot 拒绝、伪造 citation 拒绝、有限重试、401 脱敏、截断/超大结果和全局 tracing=true 时的显式禁用。测试只使用假 Key 和本地/Mock 响应，没有请求真实 DeepSeek。

## 验收边界

LangChain SDK 会先接收并解析响应，适配器随后检查结构化结果的 4 MiB 上限；这不等同于原生 provider 的接收前字节截断。回答仍要通过 RepoLens 的严格输出校验。

真实 DeepSeek 兼容性与回答质量、Docker 实机、Linux/Windows 远程 CI 尚未在本轮执行。没有修改、索引或评测学习参考仓库，没有 commit/push，也没有新增任意命令/文件写入工具。
