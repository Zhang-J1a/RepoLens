# ADR 0024：V6 工程化、安全和部署边界

状态：已采纳。对应原始路线图 V6。

后续：用户明确授权后，ADR 0025 增加可选 LangChain Core/DeepSeek 适配；标准库核心、受控 Agent 与本文的权限边界继续保留。

## 决策

- 保留本地优先和 Python 标准库核心，不为了 V6 强行引入 LangChain、LangChain4j、Redis、PostgreSQL 或 Kubernetes。
- 用标准库实现 request ID、JSON 日志、有限 metrics 和 Prometheus 文本端点；未来需要跨进程追踪时再接入 OpenTelemetry。
- 用 `Dockerfile` 多阶段构建 React 静态资源，最终镜像由 Uvicorn/FastAPI 提供同源页面和 API；SQLite 使用外置 volume，仓库只读挂载。
- 将安全边界写入威胁模型，并用 API、日志、路径、版本、prompt injection、Key 和资源上限测试验证。
- 冻结评测数据、视图和来源 hash；V6 回归脚本可以只做契约 hash 检查，也可以对指定 snapshot 重放 vector/hybrid/graph 指标。citation precision、answer accuracy 没有真实标注时保持未测量。
- 部署文档必须包含启动、配置、健康检查、故障排查、数据重建和回滚；当前不声明公开多租户部署。

## 未选择的方案

- OpenTelemetry collector：当前单进程、无外部服务的工作台不需要 collector；保留等价接口和迁移点。
- 外部数据库：任务和索引仍是单机 bounded workload，SQLite volume 足够。
- 远程模型质量门禁：真实 DeepSeek 结果受模型、网络和成本影响，未建立独立人工 gold 前不把结构化契约当作准确率。
