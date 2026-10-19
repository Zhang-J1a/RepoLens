# 开发约定

## 运行时与依赖

- 支持 Python 3.12 或更新版本。
- 运行时和测试优先使用 Python 标准库；新增依赖必须记录原因并提供离线测试方案。
- 使用 `src/` package layout，源码和数据文件使用 UTF-8。
- 测试使用 `unittest`，不联网，并通过临时 Git 仓库完成集成验证。

## 仓库与证据身份

- 证据路径统一存为仓库相对 POSIX 路径，与 Windows/Unix 工作树无关。
- 行号从 1 开始且包含两端；commit 使用 Git 返回的完整 SHA-1/SHA-256，不用缩写。
- 每个 artifact 记录 UTC 时间和 repository/snapshot 版本范围。
- 不假设 branch 名称不可变；benchmark 必须使用固定 commit SHA。
- 评测 evidence locator 必须同时能解析到文件、行范围、可选 symbol 和可检索 chunk。

## 配置与密钥

- 环境设置使用 `REPOLENS_` 前缀，并解析成 typed application settings。
- 数据目录默认使用操作系统用户数据目录，也可通过 `--data-dir` / `REPOLENS_DATA_DIR` 指定；必须位于目标仓库和 Git 目录之外。
- 不在 tracked config、fixture、错误信息或日志中放 credentials/secrets；禁止提交 `.env`。
- 默认 `mock` provider 不需要模型 key 或服务端配置。
- 选择 `answer --provider deepseek` 时，key 只能通过 `DEEPSEEK_API_KEY` 环境变量提供；模型、超时和重试可通过 `DEEPSEEK_MODEL`、`DEEPSEEK_TIMEOUT_SECONDS`、`DEEPSEEK_MAX_RETRIES` 或对应 CLI 参数覆盖。禁止把 key 写入源码、命令行参数、测试 fixture、日志、错误信息或 Git。

## 日志与错误

- 使用 Python 标准 `logging`；库代码不配置 global handlers，诊断写 stderr。
- 日志包含 operation、repository/commit 等标识，但默认不输出完整源码、secret 或 prompt payload。
- CLI exit code：成功为 0，操作失败为 1，命令行参数错误为 2。
- 错误应说明失败操作和安全下一步，不输出敏感信息或 traceback。
- 未来的 API/Agent trace 应分别记录 request/trace ID、工具状态和耗时，不把源码 excerpt 当日志元数据。

## 测试与变更策略

- 单测必须确定、离线；Git 集成测试使用临时目录。
- 每道评测题都有稳定 ID 和预期证据。修改预期答案/证据必须说明原因；新增题目使用新 ID。
- 不在没有固定真实仓库、固定 commit、数据集 hash 和运行配置的情况下宣称 retrieval/citation/latency 质量。
- 合成 Taskboard 通过只代表契约测试；Flask baseline 只代表当前固定 snapshot，不代表通用仓库表现。

## 代码编辑

- 保持模块职责窄，优先复用已有接口，不做无关重构。
- 目标仓库只读，不执行其代码，不安装其依赖，不改变其工作树或 index。
- 派生数据库、下载对象、缓存和临时 baseline 不进入目标仓库；项目是否提交评测结果按里程碑决定。
