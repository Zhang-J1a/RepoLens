# RepoLens V6 部署与回滚

## 本地源码启动

```powershell
cd D:\RAG\RepoLens
python -m venv data\v6-venv
.\data\v6-venv\Scripts\python.exe -m pip install -r apps/api/requirements-web.lock
.\data\v6-venv\Scripts\python.exe -m pip install -e . --no-deps
```

首次构建前端需要 Node 22+：

```powershell
cd apps\web
npm ci
npm run build
cd ../..
$env:PYTHONPATH = "src"
.\data\v6-venv\Scripts\python.exe -m repolens.workbench.launcher --port 8770 --no-browser --data-dir data\v6-workbench
```

浏览器访问 `http://127.0.0.1:8770/`。端口已占用时使用 `--port 0`，以终端输出地址为准。当前电脑也可双击 `RepoLens.pyw`，它复用已准备的环境、自动选端口并打开浏览器。API Key 使用环境变量或页面内存设置；不要写入 `.env` 并提交。

有构建好的 wheel 时，不需要 Node：安装锁定 Web 依赖，再用 `pip install --no-deps --force-reinstall dist/repolens-4.1.0-py3-none-any.whl`，运行 `repolens-workbench`。离线安装必须预先缓存 `requirements-web.lock` 对应当前平台的全部 wheel；本机安装验收命令见 `docs/v6-release.md`。

需要可选 LangChain 时，在相同环境改装完整锁文件 `apps/api/requirements-langchain.lock`；它包含 Web 与 LangChain Core/DeepSeek 集成的精确依赖。源码开发也可使用 `pip install -e ".[langchain]"`，具体版本以锁文件为可复现验收基线。界面选择 `LangChain + DeepSeek`，Key 的设置方式不变。适配器显式关闭 LangSmith tracing，未安装 extra 时会返回明确安装提示。

## Docker Compose

要求 Docker Engine 和 Compose v2：

```powershell
cd D:\RAG\RepoLens
docker compose up --build
```

浏览器访问 `http://127.0.0.1:8770/`，先点击“打开演示仓库”。默认配置不依赖 Flask 或任何本机参考项目。服务以非 root 用户运行，根文件系统只读，`/data` 是持久化数据卷，`/tmp` 是受限临时内存目录；前端在构建阶段打包进 FastAPI，SQLite 无需独立数据库服务。

分析自己的仓库时，确认真实路径存在，再显式启用只读挂载：

```powershell
$env:REPOLENS_REPOSITORY_PATH = "D:\your-existing-git-repository"
Test-Path -LiteralPath $env:REPOLENS_REPOSITORY_PATH
docker compose -f docker-compose.yml -f compose.repository.yml config --quiet
docker compose -f docker-compose.yml -f compose.repository.yml up --build -d --wait
```

在工作台填容器路径 `/workspace/repository`，不是 Windows 路径。容器仅允许该目录和自带 Demo；连带的 Git objects 也必须位于授权根内。linked worktree 的 Git 目录若在挂载之外，需要运维明确授权对应目录，不能自动越界读取。Docker Desktop 需要允许共享源盘符。

当前机器未安装 Docker，本轮未执行镜像构建或 Compose 启动；CI 中已经配置干净启动、Demo、可选挂载导入和挂载只读属性检查，但未运行远程 CI。

默认镜像只安装 Web 依赖。需要 LangChain provider 时可执行 `docker compose build --build-arg REPOLENS_LANGCHAIN=1`，再 `docker compose up -d --no-build`；该构建参数只选择依赖锁文件，不包含 API Key，也不改变仓库挂载权限。本机同样未执行这条可选镜像构建，不能把配置存在当作 Docker 验收通过。

## 配置和数据

- `REPOLENS_DATA_DIR`：索引、任务演示和持久化数据目录。
- `DEEPSEEK_API_KEY`：可选模型 Key，不写入镜像层或日志。
- `DEEPSEEK_MODEL`：可选模型名。
- `REPOLENS_REPOSITORY_PATH`：Compose 下可选的只读仓库挂载源。
- `REPOLENS_REPOSITORY_ROOTS`：服务可访问的仓库根目录列表，以操作系统路径分隔符分隔；同时限制新任务、工作区列表和历史证据读取。桌面未设置时由用户显式选择本地路径。
- `REPOLENS_LOG_LEVEL`：默认 INFO，JSON 日志写到 stderr；API Key、源码和请求体不写日志。

索引数据库可以删除并重建；它不是唯一事实来源。原始 Git 仓库不在容器内复制，工作台只读取挂载路径的 Git objects。

## 健康检查与回滚

- `GET /api/health` 返回服务、版本和数据目录状态。
- `docker compose ps` 查看容器和 healthcheck。
- 发布前执行 `python scripts/v6_regression.py`；若提供固定 index，再执行 `--index <path>` 重放检索指标。
- 回滚到上一个镜像：`docker compose up -d --no-build` 前先将 Compose 的 `image` 改回已验证 tag；保留 `/data` 卷，不要把新版本数据库复制进目标仓库。
- 若新 schema 不兼容，使用新数据目录重建索引；不要对原始仓库执行 reset、checkout 或恢复工作树。

## 排障与重建

| 现象 | 检查与处理 |
|---|---|
| 双击无页面 | 使用 `start_repolens_v5.bat` 保留错误输出；确认 Web 依赖和前端资源存在。路径名称沿用 V5，启动当前 V6 代码 |
| 端口占用 | 使用 `--port 0`；不要停止未知服务 |
| 仓库不存在 | 使用 `Test-Path` 和 `git -C <真实路径> rev-parse HEAD`；容器中使用挂载目标路径 |
| 403 | 检查 Host、Origin、是否从同源界面访问；服务不支持公网反向代理或跨源前端 |
| 任务失败 | 用响应 `X-Request-ID` 对照任务的 `request_id`、日志的 `task_id/trace_id`；查看 `error_code` 和 Trace stop reason |
| 缺少 Key 或 401 | 在设置中重新填写 Key，或重启前设置环境变量；不要把 Key 放进 URL 或排障截图 |
| 索引损坏/策略不匹配 | 停服务，备份整个 data 目录（包括 SQLite 辅助文件），用新的外置 data 目录重新导入固定 commit |
| 容器卷权限失败 | 查看容器日志和 volume UID，服务 UID 为 10001；不要为了修复把仓库改成可写 |
| 引用有效但结论错误 | 保存确切输出并独立标注支持度，运行生成评分器；引用定位验证不保证语义正确 |

不要在服务运行时直接复制单个 SQLite 文件作一致性备份。回滚应用前保留对应镜像 tag、wheel hash 和停服后的完整 data 副本；数据库无法向后兼容时使用新的数据卷重建。`docker compose down` 保留数据卷；不要加 `-v`，除非明确需要删除数据。

## 已知限制

V6 仍是本地单用户分析工具；没有多租户认证、远程仓库托管、运行时任务取消、OpenTelemetry collector 和真实生成质量门禁。Docker 构建需要联网下载基础镜像和 Python/Node 依赖；离线核心测试仍使用标准库和已缓存依赖。
