# ADR 0015：V4 本地浏览器界面

## 状态

已接受，适用于 V4.0.0。

## 背景

CLI 适合测试、CI 和复现，但日常使用需要先打开终端、记住参数并复制 snapshot。用户希望双击后直接在浏览器中提问，同时保留 API Key 和仓库内容的本地边界。

## 决策

1. 增加标准库实现的 `repolens.webapp`，提供 loopback HTTP 服务和内嵌静态页面；服务只允许绑定 `127.0.0.1`、`localhost` 或 `::1`。
2. 页面提供代码问答、连续对话、变更影响三个工作区，分别调用 `/api/ask` 和 `/api/impact`；后端复用既有 ingestion、pipeline、impact 和 citation validator。
3. 浏览器只把仓库路径和 index path 存在 localStorage；API Key 通过设置接口写入服务进程内存，不回显、不写文件，服务重启后失效。
4. 增加 `RepoLens.pyw` 双击入口和 `repolens-ui`/`repolens serve` 入口；CLI 保留，作为自动化和验收接口。
5. HTTP body、文本字段、预算、follow-up 次数和 provider 均有界校验；错误返回 JSON，不返回源码、prompt 或 API Key。

## 后果

- 用户可以直接打开使用，首次体验不再依赖命令行参数。
- 仍然是本地工具，不需要外部 Web 服务、数据库或前端依赖。
- API Key 不持久化；需要持久保存时仍应由用户在启动环境中设置 `DEEPSEEK_API_KEY`。
- 当前不提供远程访问、账户认证、多人协作或 compiled installer；这些属于独立发布问题。
