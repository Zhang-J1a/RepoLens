# RepoLens

RepoLens 是面向本地 Git 仓库的可直接打开的证据优先代码 RAG 应用：从指定 commit 建立索引，检索带文件、符号和行号的 evidence，按上下文预算组装，再输出经过 citation 校验的结构化回答和 commit impact 报告。当前 Python 包版本为 **4.1.0**，路线图阶段为 **V6**；两者是独立编号，阶段完成度由能力验收决定。双击 `RepoLens.pyw` 即可打开本地浏览器界面；CLI 仍保留用于测试和自动化。

V5 阶段引入完整 Web 分析工作台：仓库导入、变更报告与 diff、关系图、检索问答、Trace、评测对比；当前 V6 在此基础上补齐工程化与部署能力。`RepoLens.pyw` 启动当前主工作台，`start_repolens_v5.bat` 是保留命名的兼容启动器；详细流程见 [V5 使用说明](docs/v5-workbench.md) 和 [V6 交付记录](docs/v6-release.md)。旧标准库 `webapp.py` 与 V4 CLI/API 继续保留兼容入口。

V6 补齐冻结质量回归、独立引用/生成评分器、请求与任务日志关联、有界 metrics、安全限制、干净打包、CI 与 Docker Compose。当前实际验证和未验收项见 [V6 交付记录](docs/v6-release.md)；本机未安装 Docker，远程 CI 未执行，真实 DeepSeek 质量仍未评测。

产品不绑定 Flask，也不绑定某个项目目录。目前结构化支持 Python 和 Markdown；其他文件类型会报告跳过。工作区的 `all-in-rag` 和 `AgentGuide` 仅供个人学习，不作为产品输入。Flask 是固定版本的评测对象，Taskboard 是项目自带的合成演示数据。

## 快速运行

要求 Python 3.12+、Git 和支持 FTS5 的 SQLite。本机已验证 Python 3.12.8 / SQLite 3.45.3 / Git 2.53.0，Windows 环境。

使用已生成的 wheel 安装到自己的虚拟环境，不需要联网：

~~~powershell
cd D:\RAG\RepoLens
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --force-reinstall --no-index --no-deps dist/repolens-4.1.0-py3-none-any.whl
.\.venv\Scripts\repolens.exe doctor
.\.venv\Scripts\python.exe -I scripts/demo.py
~~~

演示脚本在临时目录复制本项目 Taskboard fixture、创建临时 Git 提交，完成 `ingest → search → evidence → snapshots`，并核对工作树未变化。它不运行被索引仓库的代码；退出时清理临时文件。输出中会看到 `TaskService.create_task` 的证据。合成演示不代表真实仓库检索质量。

本工作区另有已安装并验收通过的环境，可直接运行：

~~~powershell
.\data\v6-acceptance-venv\Scripts\python.exe -I scripts/demo.py
~~~

Linux/macOS 对应使用虚拟环境的 `bin/python` 和 `bin/repolens`。CI 已配置 Windows/Ubuntu、Python 3.12/3.13；本轮只完成本机 Windows 执行，未触发远程 CI。

## 分析自己的仓库

以下 PowerShell 流程可用于任何已获授权的本地 Git 仓库，当前只索引其中受支持的 Python/Markdown 文件：

~~~powershell
$repolens = ".\.venv\Scripts\repolens.exe"
$repository = "D:\your-project"
$indexDirectory = "D:\repolens-index"
$snapshot = & $repolens ingest $repository --ref HEAD --data-dir $indexDirectory | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "ingest failed" }
$result = & $repolens search "Service.create_task" --snapshot $snapshot.snapshot_id --retrieval hybrid --limit 5 --data-dir $indexDirectory | ConvertFrom-Json
$result.results | Select-Object path, symbol, line_start, line_end
if ($result.results.Count -gt 0) {
    & $repolens evidence $result.results[0].evidence_id --snapshot $snapshot.snapshot_id --data-dir $indexDirectory
}
~~~

`--ref` 接受本地已存在的 ref 或完整 commit SHA，默认 `HEAD`。创建索引后，查询始终使用输出的精确 snapshot ID。索引必须位于目标仓库及其 Git 目录之外；默认使用系统用户数据目录，也可用 `REPOLENS_DATA_DIR` 指定。

## 命令契约

| 命令 | 用途 |
|---|---|
| `doctor` | 检查 Python、Git、FTS5，不创建数据库 |
| `ingest <repository> --ref <ref>` | 读取 committed blobs，事务建立或重建 snapshot |
| `snapshots` | 列出当前数据库最近的 100 个 snapshot |
| `search <query> --snapshot <id>` | `keyword`、本地 `vector` 或 `hybrid` 召回，可用 `--path-prefix` 限定仓库相对路径 |
| `history <query> --snapshot <id>` | 在该 snapshot 可达的本地提交历史中检索 commit、作者和 message |
| `answer <question> --snapshot <id>` | 检索、上下文预算和结构化回答；provider 可选 `mock`、`deepseek` 或可选的 `langchain` |
| `ask <question> --repository <path>` | 自动索引仓库、选择 snapshot 并回答；默认使用 DeepSeek 和当前目录 |
| `chat --repository <path>` | 在一个 snapshot 内进行有界多轮问答；支持 `:help`、`:quit` |
| `impact --repository <path> --base <ref> --head <ref>` | 比较两个本地 commit，输出 JSON 或 Markdown 的变化文件、symbol、测试/文档/配置/历史 evidence、规则风险和建议测试 |
| `analyze commit <sha> --repository <path>` | 自动选择该 commit 的第一父提交，运行同一份影响分析报告 |
| `serve` | 启动保留的标准库兼容界面；六页面工作台使用 `repolens-workbench` |
| `evidence <id> --snapshot <id>` | 校验并返回证据行范围 |
| `evaluate <dataset.jsonl> --snapshot <id>` | 校验标注，独立计算 `keyword/vector/hybrid` 的逐题、类别和总体检索指标 |
| `evaluate-impact <dataset.json> --repository <path>` | 对固定 base/head commit 运行影响报告结构化评测，检查 F1、snapshot 绑定和 evidence 引用完整性 |
| `agent <question> --repository <path> [--ref <sha>] [--base <sha>]` | 受控多步分析：八个只读工具、共享预算、失败降级、task/trace ID；默认 Mock，DeepSeek 可选 |
| `graph --repository <path> --ref <ref> --symbol <name> --hops 2` | 返回持久化图谱的节点、边与来源；也可选文件或 commit，删除文件使用独立 base 子图 |

除 `doctor` 外以上命令均支持 `--data-dir`。stdout 为 JSON，诊断写 stderr；操作失败退出码为 1，参数用法错误为 2。无命中时 `search` 返回空列表；`answer` 会在 provider 调用前返回 `abstained`。`answer` 的模型候选只能引用本次上下文中的 `E1` 等 citation ID，RepoLens 会回填并校验真实 evidence locator。当前 Mock 输出只用于证明契约，不代表生成质量。

### V2 回答

```powershell
$env:PYTHONPATH = "src"
$snapshot = "snapshot_d157332a493291d8065f3d78825454f7479f8f6c8cbc9ea5bcb25f818a756656"
python -m repolens answer "How does Flask.test_client preserve context?" `
  --snapshot $snapshot --limit 5 --context-tokens 1200 --data-dir data/index
```

输出包含 `answer.status`、`claims`、`citations`、上下文 token 使用量以及 snapshot/commit/path/symbol/行号。没有证据或预算容纳不了完整 evidence 时，回答状态为 `abstained`，且 Mock provider 不会被调用。

### 直接提问

设置好 `DEEPSEEK_API_KEY` 后，可以跳过手动 `ingest` 和复制 snapshot ID：

```powershell
.\data\v2-acceptance-venv\Scripts\repolens.exe ask `
  "How does Flask.test_client preserve context?" `
  --repository D:\RAG\RepoLens `
  --provider deepseek `
  --data-dir D:\RAG\repolens-ask-index
```

`ask` 默认使用当前目录、`HEAD`、DeepSeek、1600 context tokens 和 1024 output tokens。第一次使用某个 commit 时建立索引，后续相同仓库和 commit 会复用已有 snapshot；commit 变化时自动建立新的 snapshot。结果的 `workflow` 字段会返回 repository、commit、snapshot、`index_action` 和索引统计。`--provider mock` 可在没有 API 请求时验证整条工作流。

### 多轮提问

```powershell
.\data\v2-acceptance-venv\Scripts\repolens.exe chat `
  --repository D:\your-project `
  --provider deepseek `
  --data-dir D:\RAG\repolens-chat-index
```

启动后逐行输入问题。`:help` 查看会话命令，`:quit` 或 `:exit` 结束会话。历史只保留最近 8 条消息；每一轮仍独立检索当前 snapshot，回答中的引用必须来自当前轮 evidence。会话不会执行目标仓库代码、修改文件或自动调用任意工具。

### 变更影响分析

`impact` 比较两个本地可用 commit。它会分别建立或复用 base/head snapshot，读取本地 Git diff，解析受支持 Python 文件的变化 symbol，并在 head snapshot 中检索相关测试和 Markdown 文档。报告中的规则风险和建议测试会标记 `inference: true`；模型层最多调用一次，且仍必须通过已有 citation 校验。

```powershell
.\.venv\Scripts\repolens.exe impact `
  --repository D:\your-project `
  --base <base-commit> `
  --head <head-commit> `
  --provider mock `
  --data-dir D:\RAG\repolens-impact-index
```

没有 API Key 时使用 `--provider mock` 做离线契约验收；需要 DeepSeek 摘要时改为 `--provider deepseek`，API Key 仍只从 `DEEPSEEK_API_KEY` 环境变量读取。`impact` 不执行目标仓库代码、不修改工作树，也不联网下载 Git objects。rename 目前按删除加新增处理。

### 直接打开使用

Windows 下直接双击项目根目录的 `RepoLens.pyw`。它会在本机启动 loopback 服务并自动打开浏览器，不显示终端窗口。页面支持：

- 代码问答：输入仓库路径和问题，使用 Mock 离线回答或 DeepSeek 回答。
- 连续对话：在同一个 commit 上追问，保留最近 8 条消息。
- 变更影响：输入 base/head commit，查看变化文件、symbol、测试、文档、风险和建议测试。

也可以在已安装环境中运行 `repolens-ui`，或使用 `repolens serve`。浏览器界面只绑定 `127.0.0.1`；索引目录在仓库之外；DeepSeek Key 通过设置页只保存在当前进程内，服务关闭后失效，不写入浏览器存储。

### 中文提问

V4.1 增加了有限、可解释的中文代码问题扩展。“入口”会增加 `main/entrypoint`，“读取”会增加 `read/load`，“写入”会增加 `write/save`，“书籍”会增加 `book/books`。代码标识符仍会原样保留，因此可以直接输入：

```text
这个项目的主要入口是什么？书籍数据如何读写？
```

这是固定检索词典，不等同于通用机器翻译或 embedding 语义检索；未覆盖的领域词仍可能需要混合文件名、函数名或英文术语。

### DeepSeek 真实回答

先在当前 PowerShell 进程设置环境变量，不要把 key 写入源码或提交到 Git：

```powershell
$env:DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
$env:DEEPSEEK_MODEL = "deepseek-flash"

python -m repolens answer "How does Flask.test_client preserve context?" `
  --snapshot $snapshot --provider deepseek --limit 5 `
  --context-tokens 1200 --output-tokens 512 --data-dir data/index
```

可选配置：`DEEPSEEK_BASE_URL`（默认官方地址）、`DEEPSEEK_TIMEOUT_SECONDS`（默认 60）、`DEEPSEEK_MAX_RETRIES`（默认 2）。CLI 也支持 `--model`、`--timeout` 和 `--max-retries` 覆盖环境变量。key 缺失、HTTP 401、超时、临时网络错误和 JSON 输出异常都会返回可读错误；模型输出仍必须通过 citation 校验。

### 可选 LangChain 集成

RepoLens 将 LangChain 用作可选的模型编排和 Retriever 适配层，不替换本地索引、SQLite、检索策略、上下文预算或引用校验。回答链使用 LCEL `ChatPromptTemplate | ChatDeepSeek.with_structured_output(...)`；`RepoLensRetriever` 把精确 snapshot 的 RepoLens 证据转换成 LangChain `Document`。Agent 仍由 RepoLens 的固定只读工具和共享预算控制，不把仓库内容交给任意 LangChain agent 工具执行。

在源码目录的虚拟环境安装可选 extra：

```powershell
python -m pip install -e ".[langchain]"
$env:DEEPSEEK_API_KEY = "你的 DeepSeek API Key"
python -m repolens ask "这个项目如何处理任务标题？" `
  --repository D:\your-project --provider langchain `
  --data-dir D:\repolens-index
```

Web 工作台在同一 Python 环境安装了 extra 后也可以将回答模型选为 `LangChain + DeepSeek`。本机离线测试不需要 API Key，也不会调用模型。适配器显式关闭 LangSmith tracing，不受全局 tracing 环境变量开启的影响；模型输入仍遵循 DeepSeek provider 的数据发送边界。详细取舍见 [ADR 0025](docs/adr/0025-optional-langchain-adapter.md)。

## 评测与边界

固定 Flask commit：`d086db856be187255b8ec61ef409357393020f32`。新建的验收索引位于 `data/v1-flask-index`，89 个源码文件、1,622 个符号、2,256 个 chunks。

| 数据集 | 题数 | Recall@5 | Recall@10 | MRR@10 | 去重证据单元 nDCG@10 |
|---|---:|---:|---:|---:|---:|
| 开发集，参与过权重选择 | 30 | 0.708 | 0.792 | 0.858 | 0.732 |
| 新冻结验证集，未用于调参 | 20 | 0.550 | 0.650 | 0.550 | 0.554 |

验证集覆盖新符号，检索前已冻结问题、28 条证据及实现 hash，之后没有针对结果调参。但它仍来自同一个 Flask commit，不是外部盲评或第二仓库泛化测试。精确标识符题 Recall@10 为 1.0，英文自然语言题为 0.6，带标识符的多方法题为 1.0，**纯中文无标识符题为 0.0**。英文源码的跨语言语义检索是后续能力。

~~~powershell
$env:PYTHONPATH = "src"
$snapshot = python -m repolens ingest data/repositories/flask --ref d086db856be187255b8ec61ef409357393020f32 --data-dir data/v1-flask-index | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "ingest failed" }
python -m repolens evaluate eval/flask-validation.jsonl --snapshot $snapshot.snapshot_id --data-dir data/v1-flask-index
~~~

此命令要求本地已有固定 Flask clone；索引不会隐式下载仓库。该 clone 是 no-checkout，空工作树状态正常。详细结果见 [V1 验收记录](docs/v1-release.md)与 [评测协议](docs/evaluation-dataset.md)。

## 工程设计

- 只读取 Git commit 对象；dirty/untracked 工作区内容不会混入历史证据。
- Python AST / Markdown ATX 分块，每块最多 80 行、重叠 15 行；语法失败有显式 fallback。
- SQLite 事务写入；keyword 使用 FTS5/BM25 召回固定 100 个候选并重排，vector 使用每个 snapshot 独立保存的本地 TF-IDF cosine，hybrid 使用固定权重 RRF 融合；history 使用独立的 snapshot-scoped FTS5 表。impact 支持 `--format json|markdown`。改变返回条数不再改变候选池。
- evidence ID 包含 snapshot、blob、路径和行号，返回前逐行核对存储的源码。
- 同名 getter/setter、重载按包含标注的具体范围校验，避免只取第一条同名定义。
- 两版基线可逐题重放；未通过门槛的融合实验保留负结果，未启用为默认。

当前限制包括：仅支持 `.py/.md/.markdown`；单文件 1 MiB、源码总量 64 MiB、tree 50,000 条；不跟随 symlink/submodule；Markdown 不是完整 CommonMark。BM25 统计跨同一数据库的 snapshot 共用，比较实验应使用固定的索引集合。路径以 UTF-8 仓库相对 POSIX 格式保存。

## 开发与验证

首次审计导入提交为 `9a2a5f6cd733caa5886fb6dfd12efa698c73ac74`（`chore: audited initial import of RepoLens V6`），后续改进按真实小提交保留，不回填 V1-V6 历史。按作者决定，当前暂不添加 `LICENSE`。

干净源码副本可以在已安装 Python 3.12+、Git、pip 和 setuptools 的环境中离线构建核心 wheel，不需要本机 `data/`、数据库或目标仓库。以下命令从项目根目录执行：

~~~powershell
python -m venv --without-pip .venv
python -m pip wheel . --no-cache-dir --no-deps --no-build-isolation --no-index --wheel-dir dist
python -m pip --python .venv/Scripts/python.exe install --no-cache-dir --no-index --no-deps dist/repolens-4.1.0-py3-none-any.whl
.\.venv\Scripts\python.exe -I -m repolens doctor
.\.venv\Scripts\python.exe -I scripts/demo.py
~~~

此流程验证核心 CLI 和合成 Demo；完整 Web wheel 还需构建前端并安装可选 Web 依赖，见[部署与源码构建](docs/deployment.md)。两种构建不能混称为完整 Web 验收。远程 CI 与 Docker 实机仍需以实际运行结果为准。

~~~powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q src tests experiments scripts
python -m pip wheel . --no-deps --wheel-dir dist
~~~

当前测试和安装验收结果见 [V6 交付记录](docs/v6-release.md)。核心运行时无第三方依赖；Web 工作台需要可选 FastAPI/Uvicorn，构建前端需要 Node。从源码构建需要 setuptools，常规隔离构建可能下载构建工具。V1 的三路真实评测及限制见 [V1.4 检索验收](docs/evaluation-v1.4.md)；V2 的结构化 impact 与 evidence 校验见 [V2 影响报告验收](docs/evaluation-impact-v2.md)；V3 的固定工具、预算、降级及 Trace 见 [V3 验收记录](docs/evaluation-agent-v3.md)；V4 持久化图、版本隔离、跨文件收益和通用任务回退见 [V4 验收记录](docs/evaluation-graph-v4.md)。真实 smoke 与同仓库 authored benchmark 不等同于跨仓库或真实模型质量。

## 文档与下一版本

- [V1 验收与安装记录](docs/v1-release.md)
- [V6 交付、偏离审计与验收边界](docs/v6-release.md)
- [部署、排障与回滚](docs/deployment.md)
- [面试讲解与演示](docs/interview-guide.md)
- [产品规格](docs/product-spec.md)
- [架构](docs/architecture.md)
- [评测协议](docs/evaluation-dataset.md)
- [V1.3 审阅及融合负实验](docs/evaluation-review-v1.3.md)
- [进度交接](docs/progress.md)
- [架构决策](docs/adr/)

按初始路线图，V1-V5 已按各自边界交付，V6 已实现本地工程化能力并逐项记录验证状态。跨文件图任务有收益，通用验证集存在回退，因此通用默认仍为 hybrid。详见 [V4 评测与边界](docs/evaluation-graph-v4.md)、[V5 使用说明](docs/v5-workbench.md) 和 [V6 交付记录](docs/v6-release.md)。动态/跨语言调用关系、Docker 实机和远程 CI 验收、真实 DeepSeek 质量评测仍待完成。使用 `deepseek` 的 `ask/chat/impact/agent` 或 Web API 才需要 API Key，密钥只保存在环境变量或服务进程内存。

## English Summary

RepoLens 4.1.0 provides a directly openable local browser UI for read-only Git snapshot indexing, exact snapshot reuse, bounded multilingual query expansion, Python/Markdown evidence retrieval, offline evaluation, bounded context packing, citation-validated structured answers, automatic `ask`, bounded multi-turn `chat`, bounded follow-up retrieval, and two-commit `impact` reports. The multilingual layer is a fixed, auditable vocabulary rather than a claim of general semantic retrieval; a real DeepSeek smoke test has passed, but this is not a claim of broad answer quality.
