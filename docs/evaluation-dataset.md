# 评测数据集与协议

作品集优化 M4 的多仓库输入、独立题集契约、冻结顺序和验收限制见 [M4 评测协议](evaluation-m4.md)。目前只有输入预检，尚无新的外部盲测结果；下方为既有评测记录。

## 数据集

- `eval/questions.jsonl`：针对项目内合成 `taskboard-v0` fixture 的 30 道题，用于契约和回归测试。
- `eval/flask-questions.jsonl`：针对固定 Flask commit 的 30 道人工问题，包含 63 条预期 evidence locator，作为当前真实仓库基线。
- `eval/flask-validation.jsonl`：V1 收尾新增的 20 道同仓库留出题，28 条 locator，覆盖未在开发集 gold 中出现的 symbol；标识符、英文自然语言、纯中文、多方法证据各 5 题。

Flask 每道题都有稳定 ID、仓库标识、完整 commit SHA、类别、查询、预期行为及一条或多条证据定位。合成 fixture 属于本项目，不来自 `all-in-rag` 或 `AgentGuide`。JSONL 格式不依赖特定评测框架。

Taskboard fixture 小而可读，主要验证契约和确定性测试；它不代表真实仓库检索质量、跨仓库泛化能力或生产性能。首批候选仓库、许可信息和固定 commit 记录在[评测仓库清单](target-repositories.md)。禁止对会变化的分支名直接跑可比较的 benchmark；必须先索引并记录确切 SHA。

## Flask 题目覆盖范围

题目覆盖路由、请求生命周期、异常处理、Blueprint、配置、上下文、helpers、测试、异步支持和架构文档。所有题目都以可定位源码为真值；当前集合没有不可回答题，因此本次不评估 abstention。

首次运行前以固定 snapshot 校验 locator，修正记录如下：

- `flask-v1-018`：将 `test_config_from_envvar_missing` 从跨测试的 144-171 行收窄到该符号的 161-171 行。
- `flask-v1-021`：将 355-377 行拆为 `test_open_resource` 355-360 和 `test_open_resource_with_encoding` 371-377，避免一个 locator 跨越多个测试。
- `flask-v1-022`：将 363-410 行拆为 `get_send_file_max_age` 363-388 与 `send_static_file` 390-410。
- `flask-v1-023`：将跨符号的 381-414 行拆为 `_get_session` 381-393 与 `match_request` 405-414。
- `flask-v1-024`：将 1420-1479 行拆为 `do_teardown_request` 1420-1451 与 `do_teardown_appcontext` 1453-1479。
- `flask-v1-026`：将 `test_filter` 的结束行从 681 收窄到该符号的 670。

这些变更使标注对应准确的源码符号，不按检索结果调整真值。后续使用前仍应人工审阅题意及证据是否充分。

## 指标定义

- **Recall@5 / Recall@10**：每道题前 K 个结果覆盖的预期 evidence locator 数，除以该题 locator 总数。总体采用题目宏平均，不是所有 locator 混合计算的 micro average。
- **MRR**：首个命中任一预期 locator 的结果排名倒数，再对题目取宏平均。未命中记为零；检索深度由 `--limit` 记录。
- **nDCG@10**：采用去重证据单元口径。结果只有引入尚未覆盖的预期 locator 时才获得二元 gain，按 `1/log2(rank+1)` 折扣；理想序列长度为 `min(10, 该题 locator 数)`。它衡量新证据排序，不让同一方法的多个重叠 chunk 反复得分。
- **Query error rate**：检索调用发生可预期 `RepoLensError` 的题目比例；记录错误并将该题检索指标计为零。
- **P50/P95 latency**：单次检索调用耗时分位数，不含数据集加载和预验证耗时。小样本本机延迟不等于生产服务 SLO。

命中要求路径一致、符号一致（若有标注）且行范围相交。重复 `evidence_id` 只处理第一次，保留原始排名位置；一个结果可以贡献多个 locator 的 Recall，但在 nDCG 中至多作为一个新相关结果计分。

每次跑分前，验证数据集仅含一个仓库/commit，并且 commit 与 snapshot 一致；每条证据的文件、行号、符号边界及可检索 chunk 都必须解析成功。不得以文件存在替代符号/行范围校验。

不要把不同指标合成会掩盖引用或版本过滤错误的总分。将来生成回答时，再分别增加 citation precision/coverage、无效引用率、结构化输出通过率和 abstention 指标。

## 运行方式

~~~powershell
cd D:\RAG\RepoLens
$env:PYTHONPATH = "src"
python -m repolens evaluate eval/flask-questions.jsonl --snapshot snapshot_d157332a493291d8065f3d78825454f7479f8f6c8cbc9ea5bcb25f818a756656 --data-dir data/index
~~~

JSON 结果记录 dataset SHA-256、commit、snapshot ID、index policy、检索配置、逐题指标、类别宏平均和延迟。V1.3 的检索策略名为 `fts5-bm25-coverage-rerank-v1`：先用 FTS5/BM25 生成最多 100 个候选，再按查询标识符覆盖率和 symbol root 做确定性重排。可比实验必须固定数据集内容、commit、检索参数与索引集合。FTS5/BM25 统计量在同一数据库的多个 snapshot 间共享，比较检索改动时应建立新的固定索引目录。

离线回归测试：

~~~powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
~~~

## 数据变更规则

V1.3 已使用 Flask 30 题进行权重选择，因此该集合现在属于开发集，不再是独立测试集。冻结当前数据和两版结果；新增验证题应独立标注，并在冻结后评估。逐题回退、标注充分性问题及未通过门槛的融合实验记录在 [V1.3 审阅报告](evaluation-review-v1.3.md)。

V1 新验证集在首次检索前通过 `flask-validation-manifest.json` 固定了数据和检索源码 hash。结果见 `flask-v1-validation.json`，R@10 为 0.650；其中纯中文题为零。没有根据结果改题或调参，详细分类见 [V1 验收](v1-release.md)。同仓库新题仍不能替代外部盲评、跨仓库验证或生成回答正确率评测。

用作回归 benchmark 后保持题目稳定。修改问题或预期证据必须说明原因并记录变更；新增题目使用新 ID。禁止为提高分数而不留记录地改写预期答案或证据。
