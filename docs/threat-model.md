# RepoLens V6 威胁模型

## 范围和信任边界

RepoLens 是本地代码分析工具。用户选择的 Git 仓库、源码注释、Markdown、commit message、PR diff 和模型响应都属于不可信数据；RepoLens 自身代码、索引目录、运行时配置和用户操作属于宿主信任边界。V6 容器只通过 `127.0.0.1` 暴露端口，Docker 数据卷是持久化边界。

## 资产

- 本地仓库内容、路径、Git commit 和索引数据库。
- DeepSeek API Key、模型请求 telemetry 和任务结果。
- 证据引用的版本、路径、行号和 source span 一致性。
- Agent 工具权限、任务预算、Trace 和评测数据。

## 主要威胁与控制

| 威胁 | 控制 | 残余风险 |
|---|---|---|
| 仓库文本包含 Prompt Injection | provider system prompt 明确将仓库内容标记为不可信；Agent 只接受宿主白名单动作 | 真实远程模型可能仍理解错误，需要独立模型质量评测 |
| 模型伪造 citation | 只接受当前 context pack 的 citation ID；未知 ID、无引用事实 claim 和非法结构 fail closed | 正确引用不等于语义支持度已经测量 |
| 历史版本混入未来证据 | snapshot 绑定完整 commit SHA；base/head 分开存储和校验 | 复杂 Git 替换、外部 submodule 不在当前覆盖范围 |
| 目标仓库代码被执行 | 只读 Git object；不 checkout、不 import、不安装依赖、不运行目标代码 | Git 本身和宿主权限仍属于操作系统信任边界 |
| 路径穿越或读取索引外文件 | repository-relative POSIX path 校验；源码/diff 从选定 snapshot 读取；配置的仓库根也限制历史证据和工作区列表 | 用户给出的仓库路径本身必须是用户有权访问的本地目录 |
| 任意 Agent 工具调用 | 固定工具注册表、严格参数、无 shell/URL/写文件权限、步数/token/结果/超时预算 | provider 适配器属于可信项目代码，不是通用 Python 沙箱 |
| API Key 泄露 | Key 只来自环境变量或当前进程内存；结构化日志和错误响应脱敏；不进入 URL、Trace、导出或 Git | 运行主机本身被攻破不在应用层保证范围 |
| 本地服务被跨站调用 | loopback 绑定、Host/Origin/Sec-Fetch-Site 校验、JSON body 上限、CSP 和安全响应头 | 浏览器插件或本机恶意进程可访问 loopback，不能替代操作系统隔离 |
| 任务无限增长 | 单线程执行、24 个任务容量、512 个事件上限、有限任务结果和 SSE 补读 | 当前不支持运行中任务取消，长任务仍占用本地资源 |
| 日志泄露源码或请求体 | V6 日志只记录 request ID、路由、状态、耗时和错误类型；不记录 body/prompt/source | 依赖或 uvicorn 自身日志需按部署配置复核 |

## 安全验证

- `tests/test_v6.py` 验证 request ID、CSP、跨源拒绝、body 上限、日志脱敏和有界 metrics。
- `tests/test_workbench.py` 验证 snapshot 隔离、删除文件 base/head、PR diff 校验、API Key 不回显和 SSE 补读。
- `scripts/v6_regression.py` 验证冻结评测视图和来源 hash；可对固定索引重放 vector/hybrid/graph 指标。
- CI 已配置干净环境的 Python 回归、Web 格式/类型/构建、API、安装包和 Playwright 门禁，以及 Docker 启动/挂载检查；本轮没有运行远程 CI，不声明这些平台已验收。
- 兼容标准库 HTTP 服务同样拒绝不可信 Host、跨站 Origin/Sec-Fetch-Site 和非 JSON POST，避免旧入口绕开内存 Key 的请求边界。

## V6 边界

当前安全目标是本地、单用户、只读分析工具。它不是多租户服务、远程仓库托管平台或生产级任意代码沙箱；公开部署前必须增加认证、租户隔离、审计存储、资源配额和独立渗透测试。
