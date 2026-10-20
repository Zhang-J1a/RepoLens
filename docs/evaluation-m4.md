# M4：多仓库外部盲测准备与验收协议

状态：输入预检已实现；目标仓库待用户提供，尚未冻结题集、运行盲测或完成 M4。

## 输入与边界

按[作品集优化计划第 8 节](portfolio-optimization-plan.md)选择 3–5 个已授权、本地存在、未参与检索调参的 Python Git 仓库。由用户提供路径及评测元数据公开范围，随后只读解析本地 HEAD，记录完整 SHA 和许可证据。首次检索前，将正式目标加入[仓库清单](target-repositories.md)。不自行下载仓库。

至少一个仓库应有较多跨文件关系，至少一个同时包含文档和测试；仓库规模、领域和目录结构应有差异。这些条件必须审阅源码目录与使用记录，不能只靠配置中的 `external_blind: true` 证明。

`all-in-rag`、`AgentGuide` 不得访问以开展本评测；既有 Flask 开发/验证集、RepoLens 自身、Taskboard fixture 和已用于 V4 中文检索开发验证的 `Book Manager V1` 不作为新的外部盲测。TypeScript 目标不能充当 Python 仓库数量。不得运行目标代码、测试、hooks、依赖安装或联网获取缺失对象。

## 输入预检

`experiments/m4_preflight.py` 只读取用户选择的计划 JSON 和其中声明的题集 JSONL，不打开目标 Git 仓库、不建索引、不检索、不调用模型、不写文件。它检查声明是否完整、仓库数、SHA 格式、全局题目 ID、每仓库题量、类别覆盖和 locator 结构，并返回输入字节 SHA-256。

预检成功只表示 `input_shape_validated`，`benchmark_ready` 始终为 `false`。它不能验证授权真实性、Git root 是否为同一仓库的别名、commit 对象是否存在、源码行号/符号是否正确、历史可达性或标注语义。输出不含 `local_path` 和授权说明；即使如此，仓库名称、提交号和结果仍须按用户许可决定能否公开。

空模板 [m4-input.example.json](../eval/m4-input.example.json) 刻意不可通过，避免把示例当真实输入。正式含本机路径的计划放在已忽略的 `data/m4/`，不提交。用户提供目标后，再生成完整本地配置。每个 `repositories` 条目包含：

| 字段 | 要求 |
|---|---|
| `id` | 稳定仓库标识，题集 `repo` 必须一致 |
| `local_path` | 用户提供的本地路径；正式 Git 校验时规范化并排除别名重复 |
| `commit_sha` | 从本地解析的完整小写 SHA-1 或 SHA-256；不使用 `main`/`HEAD` 代替 |
| `language` | `python` |
| `external_blind` | 明确为 `true`，仍需人工复核未参与调参 |
| `license` | 已核对的许可证标识，未知时填 `NOASSERTION` 并记录限制 |
| `authorization_note` | 对应用户授权的会话/记录说明，不包含密钥 |
| `publish_metadata` | 明确的布尔值；`false` 不阻止本地评测，但禁止直接公开该仓库记录 |
| `dataset` | 相对计划文件目录的 JSONL 路径，或本地绝对路径 |

顶层字段为 `schema_version: "repolens.m4-input.v1"`、非空 `annotator` 和 `repositories`。

从项目根运行：

```powershell
$env:PYTHONPATH = "src"
python -m experiments.m4_preflight --plan data/m4/input.json
```

退出码 0 表示声明/结构通过，1 表示输入不合要求，2 表示命令行参数错误。不会自动创建配置、纠正 gold 或冻结 manifest。

## 题集契约

每仓库至少 15 题，总计至少 45 题。六类均须在每仓库出现：

| `category` | 内容与 gold |
|---|---|
| `identifier` | 精确 symbol/file；至少一个源码 locator |
| `english_natural_language` | 英文自然语言；至少一个源码 locator |
| `chinese_no_identifier` | 中文且问题不含代码标识符；至少一个源码 locator |
| `cross_file` | 调用/import 关系；至少两个不同文件的源码 locator |
| `history` | 历史/commit；非空 `expected_commits`，可补充源码 locator |
| `abstention` | 无证据/证据不足；空 `expected_evidence`，无预期 commit，不编造 gold |

每题必须有非空 `id`、`repo`、`commit_sha`、`query`、`category`、`expected_behavior`、`review_notes` 和 `expected_evidence` 数组。`expected_behavior` 为 `answer` 或 `abstain`，与类别一致。`review_notes` 解释题意、证据充分性或拒答理由。问题最长 4096 字符，沿用产品上限。

源码 locator 复用现有字段 `path`、`symbol`、`line_start`、`line_end`：路径为仓库相对 POSIX 路径，行号从 1 起且包含两端，symbol 可为空。历史题的 `expected_commits` 为完整 SHA 数组，不能用当前 snapshot SHA 代替实际目标提交。

类别语义必须人工审阅，特别是中文是否混入标识符、跨文件证据是否真正构成调用关系、拒答是否成立。预检只验证结构，不证明问题或标注正确。合成预检测试不是任何真实题集。

## 首次检索前的冻结门禁

1. 根据已授权路径只读校验规范 Git root，排除同根别名和既有开发仓库；核实规模/领域/结构、Python 源码、文档/测试及许可证据。
2. 解析完整 commit SHA，并核对所有题目的仓库/版本绑定。缺失 Git objects 时停止，不联网补全。
3. 不运行检索，先由固定 Git blobs/索引结构校验源码 locator、symbol 边界和可检索 chunk。历史 gold 必须在该 snapshot 可达且位于明确记录的 history 读取边界内。
4. 记录标注者、审阅限制、冻结 UTC 时间、每题/每仓库计数、locator 数、历史 gold 数，以及题集原始字节 SHA-256。
5. 冻结 parser/index/query/retrieval/graph 策略、评测 runner 和评分器实现 hash；源码 hash 使用明确的 LF 规范化口径，数据 hash 使用原始字节口径。记录完整索引 corpus 和各策略参数。
6. 冻结后再首次检索。gold/题意错误另建数据版本并解释原因；不根据分数原地改题，不覆盖旧 manifest 或结果。

当前预检返回的 hash 只是输入指纹，不是已冻结的 manifest。正式冻结与执行 runner 尚待实现和测试。

## 报告口径

现有 `evaluation.py` 保持原契约：单仓库、每题非空源码证据、locator Recall/MRR/nDCG。因此不能直接把历史题/拒答题塞入旧评分器，或把它们的空 gold 当作 Recall=1。M4 执行层应复用既有检索和证据验证接口，独立补足报告能力。

- 同题执行 keyword、local TF-IDF vector、hybrid、graph，使用隔离的固定索引，避免其他 snapshot 改变 BM25 corpus statistics。候选、top-k、图扩展和过滤规则固定，默认 hybrid 不变。
- 小仓库 full-context 是完整源码回答对照，不是第五种检索排序。须记录模型窗口、系统/问题/输出预留与源码 token 的计数或估算口径；未授权模型/源码外发或超窗口时明确 `unavailable` 及原因，不伪造 Recall 或模型质量。
- 源码可回答题分别计算去重 file、带路径 symbol、locator 的 Recall@5/10；仅含文件 locator 的题不进入 symbol 分母。按题宏平均，报告每项分母。MRR 与去重 nDCG 沿用已有 locator 定义；跨文件部分命中不能当整题完成。
- history 单独报告 commit Recall@5/10、MRR、读取边界和缺失历史限制；同时公开各源码策略对 history 题的原始召回及适用性。不得声称源码命中证明历史题正确，或把专用 history 工具结果冒充四种源码策略的结果。
- abstention 单独保存每策略命中数和证据审阅结论；非空召回不等于可回答，零命中不等于拒答正确。实际回答拒答及精确率/召回率留给经授权的 M5 生成评测。
- 按总体、仓库、类别、逐题保存零命中率、查询错误率、P50/P95 延迟、索引时间/字节大小和增量复用分子/分母。无可用父提交或分母为零时标记 unavailable，不能编造复用率。
- 逐题配对 graph 与 hybrid，列出改善、持平、回退及失败案例。公开受许可限制的数据时先审阅，不泄露私有源码、prompt、本机路径或未获授权的仓库元数据。

## 当前完成检查

- 已实现：声明/题集结构预检及其离线合成契约测试。
- 待用户输入：3–5 个已授权本地 Python 仓库及元数据公开范围。
- 未完成：真实仓库登记、gold 标注与审阅、源码/历史验证、冻结 manifest、M4 执行与评分报告、full-context 可用性审计。
- 不据此声称：多仓库泛化、真实模型正确率提升或 M4 已交付。
