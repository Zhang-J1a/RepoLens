# V3：受控多步分析

此阶段在原有检索和 V2 规则报告上增加可审计 Agent。包版本保持 4.1.0，路线图阶段以本文件的验收项为准。

本文件保留 V3 的原始验收边界；当前 V4 已将关系工具升级为持久化一至两跳图，详见 [V4 使用说明](v4-graph.md)。通用搜索仍默认 hybrid，图增强可以显式选择。

## 启动

在 `D:\RAG\RepoLens` 中运行；已安装 wheel 时可以省略 `PYTHONPATH`，将 `python -m repolens` 换成 `repolens`。

```powershell
$env:PYTHONPATH = "src"
python -m repolens agent "Flask.test_client 的调用方和相关测试有哪些？" `
  --repository D:\RAG\RepoLens\data\repositories\flask `
  --ref d086db856be187255b8ec61ef409357393020f32 `
  --provider mock --data-dir D:\RAG\RepoLens\data\v3-agent-index
```

Mock 完全离线，使用固定规则挑选后续工具，仅用于流程验证。实际 DeepSeek 规划与回答使用 `--provider deepseek`，沿用环境变量 `DEEPSEEK_API_KEY`；不把密钥放进参数或文件。所有请求共享任务预算，模型可用时也不能执行 shell 或目标仓库代码。

需要 commit 变更分析时增加固定 base，V2 规则报告会在模型分析之前生成并保存在 `rule_report`：

```powershell
python -m repolens agent "这个改动影响哪些接口和测试？" `
  --repository D:\RAG\RepoLens\data\repositories\flask `
  --ref d086db856be187255b8ec61ef409357393020f32 `
  --base 329c32b916938d33fec41f40eb7ed854bf0b3e2b `
  --provider mock --data-dir D:\RAG\RepoLens\data\v3-agent-index
```

## 预算

| 参数 | 默认 | 含义 |
|---|---:|---|
| `--max-steps` | 8 | 所有工具尝试，包括被拒绝或失败的调用 |
| `--max-model-calls` | 6 | 规划和最终生成共用；预留最后一次给回答 |
| `--max-results-per-call` | 8 | 每次工具最多返回的条目/证据数量 |
| `--max-total-results` | 64 | 累计返回条数，重复结果也消耗额度 |
| `--context-tokens` | 2400 | 保留完整 evidence 的上下文估算预算 |
| `--output-tokens` | 768 | 每次模型输出上限 |
| `--max-total-tokens` | 32000 | 所有请求及可能重试的保守预留总量 |
| `--task-timeout` | 120 秒 | 含索引准备、规则报告、工具和模型的总截止时间 |
| `--max-retries` | 0 | Agent 的 HTTP 重试默认关闭；可显式设置 0..5 |

超时终止工作进程；步数或结果预算结束后，仍可在剩余模型/token/时间预算内生成一次已校验回答。token 不足不再请求模型。`stop_reason` 给出 `finished`、`deadline_exceeded`、`step_budget_exhausted`、`token_budget_exhausted`、`provider_failed`、`invalid_plan`、`invalid_answer`、`repeated_action` 等原因。

累计结果额度针对 Agent 的工具返回；先行的 V2 规则报告沿用 V2 的固定文件/证据上限，单独记录 evidence 数量，其耗时计入同一任务 deadline。

## 响应与 Trace

`repolens.agent.v1` 包含 task/trace ID、状态、固定 workflow、`answer.v1`、canonical evidence 定位、可选 `rule_report` 和 `repolens.agent-trace.v1`。`completed` 不表示模型事实一定正确；`degraded` 表示有失败或预算边界，已有结果仍可检查。重要断言仍必须引用当前 context 中的 citation。

每次工具启动、完成、失败/拒绝都带 task/trace ID 和 sequence。Trace 不包含源码正文、原始 prompt 和未经校验的模型文本；包含定位信息、合法工具参数、决策或输出 hash、usage、耗时和错误类别。Trace 默认只在响应内，不写数据库或日志。

本地服务提供 `POST /api/agent`，复用已有内存 key 设置：

```json
{
  "repository": "D:\\RAG\\RepoLens\\data\\repositories\\flask",
  "ref": "d086db856be187255b8ec61ef409357393020f32",
  "question": "Flask.test_client 的相关测试在哪里？",
  "provider": "mock",
  "budget": {"max_steps": 5, "timeout_seconds": 120}
}
```

原有 `ask/chat/impact` 和 `/api/ask`、`/api/impact` 保持可用，不依赖 Agent 成功。完整 Agent 交互和 Trace 查看页面现已在 [Web 工作台](v5-workbench.md) 实现；V6 增加 request ID 和任务/Trace 日志关联。

## 验收边界

- 八个固定只读工具、严格参数和 snapshot 绑定。
- 显式停止状态、共享预算、重复调用抑制、超时进程回收。
- vendor-neutral 模型决策、合法引用校验和失败降级。
- 临时 Git 仓库离线测试与固定 Flask smoke 分开记录。
- 调用关系只有一跳 AST 名称匹配候选；不宣称 V4 图谱或真实模型质量已完成。

原始路线图对应关系和取舍见 [ADR 0021](adr/0021-controlled-agent-budget-and-trace.md)，本轮确切测试结果见 [进度与交接](progress.md)。
