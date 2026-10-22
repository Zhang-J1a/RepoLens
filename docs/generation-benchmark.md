# 模型评测执行器：离线与真实模型

默认运行 Mock，验证冻结输入、预算预留、断点续跑和日志契约。执行器现在也支持显式选择 DeepSeek 或 LangChain + DeepSeek，但真实调用仍需要单独确认 provider、模型、仓库外发范围、请求数和费用上限；本地没有 API key 时不会自动调用。

## 输入

使用已存在的只读索引与精确 snapshot ID，不在执行器中自动 ingest 或下载仓库。题集为 UTF-8 JSONL，每行包含：

| 字段 | 要求 |
|---|---|
| `id` | 全局不重复的稳定 ID，1–128 字符 |
| `query` | 非空问题，最长 4096 字符 |
| `commit_sha` | 必须等于所选 snapshot 的完整提交号 |
| `category` | 非空类别，由标注者定义并审阅 |
| `answerable` | 人工事先标记的布尔值，不从检索命中推断 |

在项目根目录运行，路径和 snapshot 应替换为真实已准备的输入：

```powershell
$env:PYTHONPATH = "src"
python scripts/run_generation_benchmark.py --dataset data/generation-cases.jsonl --index data/generation-index --snapshot <snapshot-id> --output-dir data/generation-run-01 --max-calls 32 --max-planned-tokens 200000
```

真实模型运行必须显式指定 provider，并只从环境变量读取 key。下面的命令会产生真实请求和费用，运行前先完成 M5 授权停点：

```powershell
$env:DEEPSEEK_API_KEY = "<只在当前 PowerShell 会话设置，不写入仓库>"
python scripts/run_generation_benchmark.py --provider deepseek --model deepseek-flash `
  --dataset <固定 JSONL 题集> --index <外部索引目录> --snapshot <固定 snapshot> `
  --output-dir <仓库外的本地评测目录> --strategies keyword vector hybrid graph `
  --max-calls 30 --max-planned-tokens 200000
```

LangChain 适配器可以替换 provider：`--provider langchain`。它仍然复用 RepoLens 的检索、上下文预算和 citation validator，不会让模型获得 shell、写文件或选择仓库版本的权限。

默认同题比较 keyword、vector、hybrid、graph，top-k=5，context=2400、output=768，不追加检索。`--strategies` 可选择固定的策略子集。full-context 在 manifest 中显式标记 unavailable，不伪造第五组回答。

## 冻结与恢复

- `manifest.json`：题集原始字节 hash、包内 Python 实现 LF hash、snapshot/commit、index policy、完整 index corpus、策略与预算、冻结 UTC 时间。
- `events.jsonl`：每题先 fsync 写 `started` 和预算预留，再调用既有 `QuestionAnswerPipeline`；完成后记录结构化回答及 hash、canonical citations、无正文的 context 元数据和 telemetry。真实 provider 的重试预算会计入每题预留。
- `responses.json`：仅真实 provider 运行时导出，使用索引恢复 context 正文，供独立人工审阅器评分；这是本地敏感评测产物，不得未经审阅提交或公开。
- `run.lock`：拒绝两个执行器同时写同一目录。进程异常终止可能遗留锁；确认原进程已停止后人工恢复，保留原日志，不自动删除未知状态。

重复运行同一命令会跳过已开始的任务，包括已完成、失败和结果不确定的任务。部分/损坏日志会失败关闭；输入、源码或预算改变须新建输出目录。失败保留分类错误，不记录异常原文；完成输出的 hash 在恢复时再次检查。

输出目录必须位于目标仓库及 Git 目录之外；manifest、journal 和锁文件禁止为符号链接或解析到输出目录外，避免已有日志链接导致回写目标仓库。此检查不提供对恶意本机进程并发替换文件的沙箱保证。

默认不保存 request prompt 或源码正文，证据只记录定位。结构化模型回答属于独立的本地结果，不自动公开；未来真实模型可能在回答中复述源码，公开前仍需脱敏和权限审阅。输入问题保存在原题集，日志不另复制问题正文。

## 预算与结果口径

每个任务预留一次潜在模型调用及 `context_tokens + output_tokens + 2048` 的规划额度；真实 provider 会乘以其最大重试次数加一。无命中也保留预留，失败与中断不返还。此处是流程额度，不是服务商费用硬上限；结果中的 `actual_billed_tokens` 仅汇总服务商返回的 usage，`cost` 保持 null。

真实模型运行前仍需确认 provider/model/endpoint、允许发送的仓库及请求/token/费用上限。执行器记录 provider usage 和延迟；真实费用仍保持 `cost: null`，因为价格、折扣和账单不由 RepoLens 猜测。

人工审阅标签必须另存并绑定 `output_sha256`。先生成独立审阅模板，再由审阅者填写标签；模板生成不需要预先存在 judgment 文件：

```powershell
python scripts/evaluate_generation.py `
  --responses <responses.json> --create-review-template `
  --reviewer reviewer-1 --output <judgments.json>
```

审阅时为每个回答填写 `answer_correct`，并为模板列出的每个 claim/citation pair 填 `supported`；不得改动 `output_sha256`。随后以 `--judgments <judgments.json>` 运行同一脚本生成评分报告。脚本以独占创建方式写输出，避免覆盖已有人工材料。执行器和模板都不会自动生成语义标签，也不把 schema 通过误报为答案正确。

模板复用同一个 schema/citation validator；非法输出不列语义引用标签，评分时仍记为结构失败，不允许靠补标签将伪造 citation 算成合法。空白 `null` 标签不能直接评分，须由审阅者填写布尔值。标签中的 `failure_type` 留给审阅者描述错误，当前不作自动错误分类或多审阅者一致性分析。

拒答按 `answerable=false` 定义为应拒答；非法结构或 citation 输出按未拒答计，因此会成为应拒答题的漏拒。unsupported-answer rate 是合法 `answered` 输出中至少一个 citation 被标为 unsupported 的回答数，除以合法 `answered` 输出数。两项均报告总体、strategy 和 category 分组；无分母时返回 `null`。这些结果依赖独立人工标签。

专项测试覆盖恢复不重试、预算跨恢复保留、失败脱敏、未完成任务、输入/日志/输出 hash 损坏、并发锁和输出目录越界。真实模型正确率、引用支持度与拒答质量仍需在授权后运行并由独立标签评分。
