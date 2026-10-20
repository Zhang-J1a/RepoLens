# 开发与验证

RepoLens 当前公开用于展示与审阅，尚未授予开源许可。提交外部贡献前请先与作者确认接收方式和许可安排；本文件不额外授予源码使用权。

## 环境

- 核心：Python 3.12+、Git、SQLite FTS5，无第三方运行依赖。
- Web：`apps/api/requirements-web.lock`、Node 22+、`apps/web/package-lock.json`。
- 可选 LangChain：`apps/api/requirements-langchain.lock`。

在项目根目录使用独立虚拟环境。安装与首次构建见[使用指南](docs/usage.md)，不要依赖本机旧 `data/` 目录或已有索引。

## 验证矩阵

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q src tests experiments scripts
python scripts/v6_regression.py
```

Web 环境还需执行：

```powershell
python scripts/export_api.py --check
npm run format:check --prefix apps/web
npm run build --prefix apps/web
npm test --prefix apps/web
```

缺少可选依赖时，部分测试会按设计跳过；报告总测试数与跳过数，不能把跳过当作验收通过。浏览器测试需要预先准备 Playwright 浏览器。CI 另验证独立 wheel、Windows/Linux Python 3.12/3.13、Docker 启动和只读挂载。

## 变更原则

1. 先阅读 [AGENTS.md](AGENTS.md)、[架构](docs/architecture.md)、[开发约定](docs/development-conventions.md)和相关测试。
2. 按职责做小范围变更，保留已有用户改动，不因文件较长就机械拆分。
3. Git 集成测试使用临时合成仓库；不运行、修改或安装被分析仓库的代码和依赖。
4. 修改检索、解析、上下文或 Agent 策略时，显式记录新策略及迁移边界。不得覆盖冻结 gold 或旧评测结果制造更好的指标。
5. 提交说明包含行为、原因、验证与限制；真实模型结果与 Mock / fixture 结果分别报告。

## 提交前检查

`git diff --check` 应通过。不要提交 `.env`、API Key、下载仓库、虚拟环境、索引数据库、构建缓存或未获授权的源码/截图。新依赖、源码外发、真实模型费用、tag/release 与许可证变更须单独确认。

当前优化计划和执行状态分别见[计划](docs/portfolio-optimization-plan.md)与[交接记录](docs/progress.md)。M4 暂缓不代表跨仓库盲测已完成。
