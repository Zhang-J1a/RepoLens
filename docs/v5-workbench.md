# V5 Web 分析工作台

V5 对照原始路线图第 9 节：提供六个页面、可打开的 Git 证据、只读代码/diff、关系图、报告导出、任务进度和失败过程。包版本仍为 4.1.0，路线图阶段以能力验收为准。

## 当前电脑直接使用

双击项目根目录的 `RepoLens.pyw`。启动器优先使用已准备的 `data/v5-web-venv`，自动选择空闲端口并打开浏览器，不需要手动启动前后端两个进程。

如果 Windows 没有正确关联 `.pyw`，双击项目根目录的 `start_repolens_v5.bat`。这个入口会保留终端窗口并显示启动错误，适合排查 Python 关联问题。也可以在 PowerShell 中直接运行：

```powershell
cd D:\RAG\RepoLens
$env:PYTHONPATH = "D:\RAG\RepoLens\src"
& "D:\RAG\RepoLens\data\v5-web-venv\Scripts\python.exe" -m repolens.workbench.launcher --data-dir "D:\RAG\RepoLens\data\v5-workbench"
```

看到 `http://127.0.0.1:<端口>/` 后，用浏览器打开该地址；终端窗口需要保持运行。

已有测试服务的地址见当前交付消息。关闭浏览器标签不会自动停止服务；任务和模型 Key 仅保留在服务进程内，重启会清空，仓库索引仍保留。

## 完整演示

1. 在“仓库工作区”点击“打开演示仓库”。系统仅创建项目自带的合成 Taskboard 仓库，包含两个提交；不下载仓库，也不执行演示仓库代码。
2. 索引完成后可查看文件、提交、解析诊断及版本。也可输入自己真实存在的本地 Git 仓库路径导入；不要填写示例占位路径。
3. “变更分析”使用 Base=`HEAD~1`、Head=`HEAD`，运行分析。查看文件 diff、变化符号、风险、建议测试、相关证据和不确定性；点击证据打开代码与行号。右上角下载 Markdown 或 JSON。
4. “代码关系图”选择函数，输入 `TaskService.create_task`，选择 1 或 2 跳。可以拖动节点、缩放、筛选类型、聚焦路径、点击边看来源、从节点重新展开。存在删除文件时，Base 图和 Head 图分开选择。
5. “检索与问答”输入 `TaskService.create_task 如何处理任务标题？`。默认 Mock 用于离线演示；检索模式可查看排名、类型和分数，问答模式可打开每条结论的引用。
6. “Trace 调试”运行 `TaskService.create_task 的调用方和相关测试有哪些？`。可以设置步数/超时、查看实时工具步骤与最终 token 用量、输入/输出摘要、失败和降级。最大步数设为 3 可以演示预算结束后的保留结果。
7. “评测对比”展示 Flask 冻结实验，切换跨文件 10 题与原有 20 题，对比 vector/hybrid/graph。单题显示人工预期与实际召回定位；导入对应 Flask commit 后可打开代码。引用语义支持度和回答准确率没有真实评测，界面显示“未评测”。

## DeepSeek

打开“模型设置”，选择 DeepSeek，填写 Key 并保存；也可在启动服务前设置 `DEEPSEEK_API_KEY`。设置接口不返回 Key，浏览器存储只记住工作区 ID，不保存 Key。使用 DeepSeek 会向该服务发送当前打包的代码证据。

Mock 只检查交互和引用契约，不代表真实问答质量。默认检索仍为 hybrid；graph 在固定跨文件任务有收益，在原验证集有回退。

## PR diff 与版本

支持本地已有 commit SHA/分支；每次分析先固定成完整 SHA。PR diff 接受与所选 base/head 一致的 unified diff（3 行上下文、不检测 rename），例如 `git diff --no-ext-diff --no-textconv --no-renames --unified=3 BASE HEAD --` 的内容。系统比较变更内容，拒绝不匹配输入，不访问 GitHub、不抓取对象、不应用 patch。

历史证据从索引 snapshot 读取，不能打开当前工作树来代替旧版本；删除文件在 Base 侧显示。二进制、超大文件、symlink 或没有可显示文本的文件会明确报错。当前结构解析和关系图仍以 Python/Markdown 为主。

## 首次安装或换电脑

需要 Python 3.12+、Git、支持 FTS5 的 SQLite；从源码构建前端额外需要 Node 22.12+。下面只安装 RepoLens 自己的依赖，不安装目标仓库依赖。

```powershell
cd D:\RAG\RepoLens
python -m venv data/v5-web-venv
.\data\v5-web-venv\Scripts\python.exe -m pip install -r apps/api/requirements-web.lock
cd apps/web
npm ci
npm run build
cd ../..
```

随后双击 `RepoLens.pyw`。已构建 wheel 包含前端资源、合成 Demo 与评测视图，最终用户不需要 Node：安装带 `web` extra 的 wheel，运行 `repolens-workbench`。单独安装无 extra 的核心包仍可使用原 CLI/标准库界面。

开发模式：

```powershell
$env:PYTHONPATH = "src"
.\data\v5-web-venv\Scripts\python.exe -m repolens.workbench.launcher --port 8770 --no-browser --data-dir data/v5-workbench
# 另一个终端
cd apps/web
npm run dev
```

Vite 通过同源代理访问 API，不开放 CORS。生产构建由 FastAPI 同源托管；`/docs` 和 `/openapi.json` 可查看接口约定。服务仅绑定 loopback，校验 Host/Origin/JSON body。

## 验证与限制

```powershell
$env:PYTHONPATH = "src"
.\data\v5-web-venv\Scripts\python.exe -m unittest discover -s tests -q
cd apps/web
npm run typecheck
npm run build
$env:REPOLENS_WEB_URL = "http://127.0.0.1:8770"
npm test
```

Playwright 在本机使用 Edge，CI 使用 Chromium。测试没有 DeepSeek 请求，不能代替真实模型评测。V6 当前桌面与 390px 窄屏截图保存在 `data/v6-screenshots`；V5 截图作为历史记录保留。任务排队单线程执行，最多保留 24 个任务；容量满时先淘汰已结束任务，服务重启后任务 URL 失效；用户应及时导出需要保留的报告。

SSE 对已存在任务可按 Last-Event-ID 补读，连接中断后前端也通过轮询补查状态。索引阶段显示阶段状态，不伪造逐文件完成百分比。现阶段不提供取消索引/问答任务；Agent 仍有既有进程超时和预算边界。Monaco 作为按需加载的编辑器仍较大，首开代码可能比页面加载慢。

V6 的容器部署、统一监控和完整生成质量评测未计入 V5 完成声明。
