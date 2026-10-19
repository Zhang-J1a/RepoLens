# V1.4 检索验收记录

本次验收对应路线图 V1 的 keyword、vector、hybrid 三条检索路径和 Git history 索引。评测使用固定 Flask commit `d086db856be187255b8ec61ef409357393020f32`、20 道冻结验证题、28 条 evidence locator，数据集 SHA-256 为 `2950d7b188a3ebaf58fc1623c465ce5edd1e5a8b5cb6f11aac760f45eec7f6fc`。

索引 snapshot 为 `snapshot_74361af51599db4482b7235a0d9832780863972bb97afc8420abcb32c336889f`，policy 为 `git-objects-v3_ast-md-atx_lines80-overlap15_local-tfidf-v1_history-v1`。该 commit 当前位于本地 branch `main`。索引包含 236 个 tree 条目、89 个已索引文件、1,622 个 symbol、2,256 个 chunks 和 5,000 条有界历史提交。

| 路径 | Recall@5 | Recall@10 | MRR@10 | nDCG@10 | P50 ms | P95 ms | 查询错误 |
|---|---:|---:|---:|---:|---:|---:|---:|
| keyword | 0.550 | 0.650 | 0.550 | 0.559 | 9.864 | 17.867 | 0 |
| vector（本地 TF-IDF） | 0.458 | 0.533 | 0.387 | 0.403 | 67.762 | 77.453 | 0 |
| hybrid（加权 RRF） | 0.525 | 0.608 | 0.518 | 0.510 | 104.648 | 112.915 | 0 |

结论：三条路径都能离线复现并通过 evidence 校验；在这组单仓库验证集上，本地 TF-IDF 没有超过 keyword 基线，hybrid 也没有超过 keyword。vector/hybrid 作为可替换检索基线完成了路线图契约，但不能据此宣称语义质量提升。历史索引通过临时 Git 仓库测试和真实 Flask schema 迁移验收；历史读取上限为 5,000 条提交。

原始 JSON 结果：`eval/flask-v1.4-keyword.json`、`eval/flask-v1.4-vector.json`、`eval/flask-v1.4-hybrid.json`。这些结果仍是同一仓库的冻结验证，不代表跨仓库泛化或生产性能。
