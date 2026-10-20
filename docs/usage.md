# 使用指南

RepoLens 分为标准库核心 CLI、可选 Web 工作台和可选模型适配。首次运行先使用自带合成 Demo，不需要 API Key 或额外下载评测仓库。

## 选择运行方式

| 方式 | 前提 | 入口 |
|---|---|---|
| Docker Web | Docker Engine / Desktop、Compose v2、Git | 项目根目录 `docker compose up --build` |
| 源码 Web | Python 3.12+、Git、Node 22+，完成下方准备 | `.venv` 中的 `repolens-workbench` |
| 核心 Demo / CLI | Python 3.12+、Git、SQLite FTS5 | `.venv` 中的 `python -I scripts/demo.py` |

完整命令见[部署文档](deployment.md)。默认 Web provider 为 Mock；它只验证流程，不生成真实模型质量证据。容器的 8770 端口只发布到 `127.0.0.1`；端口占用时设置 `REPOLENS_HOST_PORT` 为其他可用端口。

## Windows 源码 Web

在源码根目录执行。首次安装和前端构建需要联网获取项目依赖；不要安装被分析仓库的依赖。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r apps/api/requirements-web.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
npm ci --prefix apps/web
npm run build --prefix apps/web
.\.venv\Scripts\repolens-workbench.exe --port 0
```

服务自动选择空闲端口并打开浏览器。完成准备后，可直接双击 `.venv\Scripts\repolens-workbench.exe`；使用 `RepoLens.pyw` 时需要以该虚拟环境的 `pythonw.exe` 打开它，例如：

```powershell
.\.venv\Scripts\pythonw.exe RepoLens.pyw
```

启动器也兼容此前准备过的 `data/v5-web-venv`，但它不是 GitHub 下载后自带的环境。旧的 `repolens-ui` / `serve` 是标准库兼容界面；六页面工作台使用 `repolens-workbench`。

## 第一次操作

1. 在仓库工作区点击“打开演示仓库”，查看固定 commit、文件和索引信息。
2. 在检索与问答页搜索 `TaskService.create_task`，打开返回证据查看文件、符号和行号。
3. 比较演示仓库的 `HEAD~1` 与 `HEAD`，查看变更、相关测试/文档和推断项。
4. 查看图和 Agent Trace；评测页展示已有冻结结果，不会因打开页面启动模型评测。

这些操作只针对项目内的合成 fixture，不执行 fixture 的应用代码或测试。Mock 回答适合验证 schema、引用和失败路径。

## 分析自己的仓库

选择已有且获授权的 **Git 仓库根目录**。ZIP 解压目录通常没有 `.git`，不能直接按 Git commit 索引。PowerShell 可先检查：

```powershell
$repository = (Get-Location).Path
git -C $repository rev-parse --show-toplevel
git -C $repository rev-parse HEAD
```

上述默认选择当前项目，实际使用时改为自己的真实 Git 路径。索引以 committed blobs 为准，不包含尚未提交的文件修改。数据库必须位于目标仓库及其 Git 目录之外，默认由 RepoLens 选择系统用户数据目录。

核心 CLI 的自包含示例，在 RepoLens 源码根目录执行：

```powershell
$python = ".\.venv\Scripts\python.exe"
& $python -m repolens doctor
& $python -m repolens ask "GitRepository 如何读取固定版本？" --repository . --provider mock
```

也可手动保存 snapshot ID 复现检索：

```powershell
$snapshot = & $python -m repolens ingest . --ref HEAD | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw "ingest failed" }
& $python -m repolens search "GitRepository" --snapshot $snapshot.snapshot_id --retrieval hybrid
```

Web 在宿主机运行时输入宿主路径；Docker 中需要配置 `compose.repository.yml`，填写容器内的 `/workspace/repository`。挂载配置见[部署文档](deployment.md)。

## 接入 DeepSeek

网页设置中的 Key 只保存在当前服务进程内存，服务重启后需要重新设置。也可以在启动服务前设置 `DEEPSEEK_API_KEY` 环境变量；不要将密钥放进命令行参数、仓库文件、截图或提交记录。

Key 已由自己在环境中设置后：

```powershell
.\.venv\Scripts\python.exe -m repolens ask "GitRepository 如何防止联网读取？" --repository . --provider deepseek
```

默认模型由 `DEEPSEEK_MODEL` 或 provider 默认值决定，可用 `--model` 显式指定；超时和重试分别由 `DEEPSEEK_TIMEOUT_SECONDS`、`DEEPSEEK_MAX_RETRIES` 或 CLI 选项控制。具体当前配置见 `python -m repolens ask --help`。真实调用会将有界源码证据发送到所选 endpoint，使用前确认仓库许可和费用预算。

可选 LangChain 使用 `.[langchain]` extra；复现完整锁定环境使用 `apps/api/requirements-langchain.lock`。安装方式、LCEL / Retriever 的职责和 tracing 限制见 [LangChain 集成](langchain-integration.md)。它不改变 RepoLens 默认检索或引用验证。

## 返回结果怎样理解

| 字段或状态 | 含义 |
|---|---|
| `commit_sha` / `snapshot_id` | 本次证据所属的固定版本 |
| `path` / `symbol` / 行号 | 规范的源码定位；点击可查看引用范围 |
| `answered` | 回答通过结构与引用校验，仍需判断语义是否被源码支持 |
| `abstained` | 无足够证据、预算不足或回答未通过验证 |
| `inference` | 规则或静态关系推断，不是执行验证的事实 |
| `degraded` / Trace stop reason | 任务因预算、超时或模型失败降级，检查仍保留的证据和报告 |

中文提问可使用，但目前是有限词典扩展。未覆盖领域时加入代码标识符或文件名更容易定位。向量为本地 TF-IDF，不能将它描述为跨语言神经语义检索。

## 常见问题

| 问题 | 处理 |
|---|---|
| 双击没有打开 | 先用准备好的环境运行 `repolens-workbench`，检查依赖和前端构建 |
| Repository path does not exist | 选择真实目录，避免照抄 `D:\your-project` 一类占位路径 |
| Git read failed | 核对目录是否有 Git 历史，以及目标 commit 是否已在本地；RepoLens 不自动 fetch |
| 模型没有 Key | 选择 Mock 验证流程，或在当前服务内设置自己的 Key |
| 模型回答有引用但结论不对 | 引用校验只证明定位有效；结合源码审阅，不以 citation 格式替代语义评测 |
| 页面显示旧数据 | 核对所选仓库和 commit；新版本会建立新的 snapshot |

更多排障、数据目录和回滚见[部署文档](deployment.md)。
