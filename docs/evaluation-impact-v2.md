# V2 影响报告样例验收

使用固定 Flask 仓库本地可用的完整 commit，从当前验证版本向可达历史选择 10 个真实 commit，每个 commit 与第一父提交组成一个 base/head 分析任务。所有任务使用 deterministic provider-free impact pipeline。

结果：10/10 case 成功，没有运行错误；其中 6 个报告为 `complete`，4 个报告为 `partial`，`partial` 表示当前 snapshot 缺少相关测试或文档 evidence，系统没有把“未检索到”当成“不存在”。样例摘要位于 `eval/flask-impact-v2-samples.json`，包含 commit SHA、父提交、变更文件和 symbol 数量、有限 caller/callee、测试/文档/配置/历史关联数量、风险级别、unknown 数量和 base/head snapshot ID；不包含上游源码正文。本轮共记录 183 个 caller 和 15 个 callee 关系。

结构化评测结果位于 `eval/flask-impact-v2-evaluation.json`，数据集 SHA-256 为 `c07b8d6b0045b56da8b415bb7a817845c4b406b3f0d7e36e8ea0478d359b9b99`。changed files、changed symbols、related tests、related docs 和 risk severity 的 macro precision/recall/F1 均为 1.0；schema validity、snapshot binding、evidence validity 和 reference binding 均为 1.0。

这项结果证明 report envelope 和有限 Python AST 关系在 10 个真实 commit 上可以运行并保持 snapshot 绑定，也证明当前人工复核结构化 gold 的契约指标。它不证明动态调用、跨语言调用方/被调用方召回、生产风险召回或跨仓库泛化质量；这些指标需要独立的动态/跨语言人工标注集。

CLI 入口包括 `impact --base <sha> --head <sha>` 和 `analyze commit <sha>`；后者自动使用目标 commit 的第一父提交。两者共享同一 deterministic report builder。
