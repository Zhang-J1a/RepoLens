# V3 受控 Agent 验收

日期：2026-10-19。按原始路线图第 7 节验收，运行时仍为 Python 标准库。

本文件保留 V3 交付时的实验与产物记录；当前 V4 的图策略、安装包 hash 和新测试结果以 [当前进度](progress.md) 与 [V4 评测](evaluation-graph-v4.md) 为准。

## 确定性测试

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -q
python -m compileall -q src tests experiments scripts
git diff --check
```

本轮全量 123 项通过，耗时 93.156 秒。其中 Agent 专项 18 项；另增加 2 项 DeepSeek 适配协议/序列化测试和 1 项 HTTP Agent API 测试，保留既有 102 项回归。`compileall`、`git diff --check` 通过；由于项目尚无 Git commit，另用空文件与改动文件逐一 `git diff --no-index --check` 检查新建/未跟踪文件，最终 21 个改动文件均无空白错误。额外检查使用 `cr-at-eol` 识别 Windows CRLF；JSON 依据 `.gitattributes` 保留原始字节，避免改变样例 hash。

| 原始 V3 验收项 | 本轮证据 |
|---|---|
| 只能调用白名单工具 | 八个工具均有调用测试；shell、repository/snapshot override、路径越界、非法范围及超量 limit 被拒绝 |
| 每次调用关联 task/trace ID | 正常与失败事件均带 ID；回答与 V2 规则报告使用同一 trace ID；HTTP API 返回相同 envelope |
| 失败可解释且无无限重试 | 分类错误、连续两次失败停止、重复调用停止、所有步骤/模型/token/结果预算受限 |
| 固定输入与配置可复现实验 | 离线同一仓库/commit 两次运行的工具序列、参数与 canonical evidence 相同；ID 和耗时允许变化；DeepSeek Agent 固定 temperature=0 并记录模型配置 |
| Agent 不可用基础能力仍可用 | provider 故障、非法规划及伪造引用时保留证据和 V2 规则报告；既有问答/impact 回归仍通过 |

超时测试覆盖独立工具工作进程和阻塞模型；结束后 `multiprocessing.active_children()` 不增加。未来版本文件和提交不进入固定 snapshot 证据；目标仓库 dirty 状态前后相同。恶意仓库文档无法增加工具权限。

## 固定真实仓库 smoke

使用本地 Flask commit `d086db856be187255b8ec61ef409357393020f32`，第一父提交 `329c32b916938d33fec41f40eb7ed854bf0b3e2b`，复用外置索引 `data/v1-flask-index-v2`：

```powershell
python scripts/agent_smoke.py `
  --repository data/repositories/flask `
  --ref d086db856be187255b8ec61ef409357393020f32 `
  --data-dir data/v1-flask-index-v2 `
  --output eval/flask-agent-v3-smoke.json
```

| 场景 | 结果 | 工具步数 | 模型调用 | 工具累计结果 | 保留证据 |
|---|---|---:|---:|---:|---:|
| 离线规则规划＋Mock 回答 | completed / answered | 6 | 1 | 34 | 15 |
| 模拟 provider 不可用 | degraded / abstained | 2 | 1 次失败 | 9 | 9 |

两种场景都保留 V2 规则报告。成功场景 25 个 Trace 事件、约 7.25 秒；失败场景 11 个事件、约 2.75 秒。这是本机已有索引的单次运行，不能当作延迟分位数或性能保证。

样例 `eval/flask-agent-v3-smoke.json` 的 SHA-256：`6440e99bfb2ad7e6a1a272a2e7f3055dbea3409a59883487e3721b75fb69db02`。样例包含 task/trace ID、步骤参数、证据定位、状态、usage 和输出 hash，不复制上游源码。此处的故障来自测试 provider，不是真实 DeepSeek 宕机测量。

## 结论与限制

本轮完成 V3 的受控工具、状态机、预算、失败降级与 Trace 契约，不把 fixture/smoke 当作真实 Agent 问答质量。没有调用真实 DeepSeek API，没有使用真实 API Key；DeepSeek JSON 协议与 spawn 兼容性使用离线测试验证。真实服务兼容性、任务成功率、成本和结论支持度需要单独的真实模型评测。

调用关系是已有 Python AST 名称匹配候选，标记 inference，仅一跳；没有引入 V4 持久化图谱或宣称动态关系正确。历史提交是检索线索，不能伪装为 `answer.v1` 的源码引用。V2 规则报告有独立的固定上限；Agent 累计结果预算只统计 Agent 工具返回，总 deadline 同时覆盖两个阶段。

当前验收平台为本机 Windows / Python 3.12；Windows/Ubuntu 的 CI 配置保留，未触发外部 CI，不能将其视为已在其他平台执行通过。

## 安装包

使用 `--no-build-isolation --no-index --no-deps` 重建 wheel，在新建的 `data/v3-acceptance-venv` 离线安装。`python -I` 验证导入来自 site-packages；doctor 通过；通过已安装包的 `agent` CLI 对相同 Flask commit/base 执行 Mock 分析，返回 completed/answered、6 步、25 个事件并保留规则报告。

直接执行已安装的 `repolens.exe` 控制台入口并设置 `--max-steps 3` 也通过，返回 degraded/step_budget_exhausted，同时在剩余生成预算内给出经过引用校验的 answered，证明 Windows 控制台入口与预算结束路径均可用。

当前产物 `dist/repolens-4.1.0-py3-none-any.whl`，SHA-256 为 `d7fc32f50c7edb3d4f2af97d742b6b7691442bc42e87e8b538c07621407497dd`。包版本未变，V2 的旧 hash 仅保留为历史记录。
