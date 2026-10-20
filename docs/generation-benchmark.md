# 模型评测执行器：离线准备

当前只支持 Mock，验证冻结输入、预算预留、断点续跑和日志契约。没有开放真实 DeepSeek / LangChain 调用，因此不要求 Key，不产生真实费用，不代表 M5 质量评测已完成。

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

默认同题比较 keyword、vector、hybrid、graph，top-k=5，context=2400、output=768，不追加检索。`--strategies` 可选择固定的策略子集。full-context 在 manifest 中显式标记 unavailable，不伪造第五组回答。

## 冻结与恢复

- `manifest.json`：题集原始字节 hash、包内 Python 实现 LF hash、snapshot/commit、index policy、完整 index corpus、策略与预算、冻结 UTC 时间。
- `events.jsonl`：每题先 fsync 写 `started` 和预算预留，再调用既有 `QuestionAnswerPipeline`；完成后记录结构化回答及 hash、canonical citations、无正文的 context 元数据和 telemetry。
- `run.lock`：拒绝两个执行器同时写同一目录。进程异常终止可能遗留锁；确认原进程已停止后人工恢复，保留原日志，不自动删除未知状态。

重复运行同一命令会跳过已开始的任务，包括已完成、失败和结果不确定的任务。部分/损坏日志会失败关闭；输入、源码或预算改变须新建输出目录。失败保留分类错误，不记录异常原文；完成输出的 hash 在恢复时再次检查。

输出目录必须位于目标仓库及 Git 目录之外；manifest、journal 和锁文件禁止为符号链接或解析到输出目录外，避免已有日志链接导致回写目标仓库。此检查不提供对恶意本机进程并发替换文件的沙箱保证。

默认不保存 request prompt 或源码正文，证据只记录定位。结构化模型回答属于独立的本地结果，不自动公开；未来真实模型可能在回答中复述源码，公开前仍需脱敏和权限审阅。输入问题保存在原题集，日志不另复制问题正文。

## 预算与结果口径

每个任务预留一次潜在模型调用及 `context_tokens + output_tokens + 2048` 的规划额度。无命中也保留预留，失败与中断不返还。此处是离线流程额度，不是服务商 token 计量或真实费用硬上限；结果中的实际计费 token 与 cost 保持 null。

后续开放真实模型前，仍需确认 provider/model/endpoint、允许发送的仓库及请求/token/费用上限，并实现服务商计量、重试和未知费用的保守处理。本轮没有绕过该停点。

人工审阅标签必须另存并绑定 `output_sha256`。当前日志包含输出及引用元数据；要使用既有生成评分器，需用同一 snapshot 的 `IndexStore.evidence` 在内存重新取得正文，并将原题、输出、标签组装成评分器输入。自动导出和真实模型 runner 留待后续 M5 切片，不将已验证输出误报为原始模型 schema 通过率。

专项测试覆盖恢复不重试、预算跨恢复保留、失败脱敏、未完成任务、输入/日志/输出 hash 损坏、并发锁和输出目录越界。真实模型正确率、引用支持度与拒答质量仍未测量。
