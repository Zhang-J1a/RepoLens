# V4 图谱与检索验收

本轮按原始路线图第 8 节实施。真实仓库固定为 `pallets/flask` commit `d086db856be187255b8ec61ef409357393020f32`，评测使用新的单 snapshot 索引 `data/v4-flask-index`。没有模型调用或 API Key，也不执行目标仓库代码。

## 跨文件比较

题集 `eval/flask-graph-crossfile-v4.jsonl` 共 10 个 authored 跨文件任务、21 条证据，涵盖测试到实现、导入/重导出、继承方法、上下文工厂和 JSON 入口，并保留动态 fixture 边界题。SHA-256：`bebcf21be9468d9ddee8383ed257ee55243d88f017fb267270d9dae2810ba857`。

最终图策略为 `python-import-scope-graph-v2`，检索策略为 `vector-static-graph-rrf-v2`。比较使用相同源码 snapshot、向量模型、top-10 和 source-span 验证；graph 允许额外的有界图扩展，所以计算量并不等同于纯向量。向量候选为 100；图最多 8 个初始种子（无精确标识符时使用前 5 个向量命中）、两跳、120 个节点、300 条边，每个节点最多 2 个 chunks。权重和排序在运行前固定，没有根据评测结果调整 gold 或排序参数。

| 策略 | Recall@5 | Recall@10 | MRR | nDCG@10 | 本机检索 P95，ms |
|---|---:|---:|---:|---:|---:|
| vector | 0.6000 | 0.8000 | 0.5100 | 0.5373 | 72.76 |
| hybrid | 0.6667 | 0.8500 | 0.8667 | 0.7290 | 117.44 |
| graph | 0.9500 | 0.9500 | 0.9500 | 0.9226 | 207.63 |

三路均没有 query error。图相对纯向量的 Recall@10 提升 0.15、相对 hybrid 提升 0.10，同时增加了耗时。10 题配对比较为 3 题提高、1 题回退、6 题相同；回退是 `flask-graph-v4-010`：纯向量 1.0，graph 0.5。该题通过 app fixture 调用生产方法，当前图无法保证动态接收者类型，邻域重排也可能挤出正确证据。

这组任务由开发者根据公开源码构造，检索前冻结，不是外部盲评、第二仓库泛化测试或答案事实一致性评测。10 题的延迟分位数也不是生产性能保证。

## 补充通用验证集

使用原有冻结的 `eval/flask-validation.jsonl` 20 题，SHA-256 为 `2950d7b188a3ebaf58fc1623c465ce5edd1e5a8b5cb6f11aac760f45eec7f6fc`，未改标签：

| 策略 | Recall@5 | Recall@10 | MRR | nDCG@10 |
|---|---:|---:|---:|---:|
| vector | 0.4583 | 0.5333 | 0.3871 | 0.4030 |
| hybrid | 0.5250 | 0.6083 | 0.5183 | 0.5096 |
| graph | 0.5000 | 0.5000 | 0.4100 | 0.4251 |

图在该集合 Recall@10 低于 vector 和 hybrid。相对 vector，016/020 提高，017/018/019 回退；未按这组结果改标签或调图权重。通用问答与 Agent `search_code` 因此保留 hybrid 默认，graph 为显式选择；关系/子图工具使用持久化图。原始结果位于 `eval/flask-graph-v4-validation-scope-v2-{vector,hybrid,graph}.json`。

## 图谱来源与覆盖

当前单 snapshot 有 2,080 个节点、4,616 条边。其中静态 calls 为 740、tests 为 505、imports 为 254、implements 为 76、depends_on 为 109；其余是定义、包含和本 commit 的修改来源。构建记录 2,718 个未解析调用、418 个未解析导入，包含内建函数、外部依赖和动态 receiver，不能把这些计数直接当成关系召回率。

Flask 有 6 个已索引 Markdown 文档节点，但当前没有可唯一定位的完整符号名提及，未生成 documents 边。此边在合成仓库中有正例验证；没有为填满图谱而推测文档关系。当前 snapshot 也不需要 interface 或 replaces 边；schema 支持其类型，缺少可信来源时不生成。

每个节点/边的 source span 或 Git commit/blob 均可追溯；API 查询再次验证版本和位置。边端点通过复合外键限制在同一 snapshot。更老版本的查询保持自己的图；被删除源码只在单独 base 图返回。

## 冻结与实验修订

首次运行的 `flask-graph-v4-manifest.json` / `flask-graph-v4-evaluation.json` 保留。随后发现通用 evaluator 的候选池标签没有说明图扩展预算，仅修正测量元数据，以 `flask-graph-v4-final-manifest.json` / `flask-graph-v4-final-evaluation.json` 重跑；所有数值质量指标与首跑相同。

最终收口又修正方法裸名称的类作用域查找和嵌套 receiver 遮蔽，增加独立回归用例，并升级图策略至 v2；没有改题集和排序权重。新冻结清单为 `eval/flask-graph-v4-scope-v2-manifest.json`，SHA-256 为 `6b9b55e63d3dbfe2e9518769390c9d2fc3396c5146cfca786d8a864bb9b50549`；结果 `eval/flask-graph-v4-scope-v2-evaluation.json` 的 SHA-256 为 `665b20e706a80c4f918b4911e490a5cba08831162d3db25bc136f41536e573f0`。最终数字以 v2 为准。

## 重现

```powershell
$env:PYTHONPATH = "src"
python scripts/graph_benchmark.py `
  --repository data/repositories/flask `
  --ref d086db856be187255b8ec61ef409357393020f32 `
  --data-dir data/v4-flask-index `
  --dataset eval/flask-graph-crossfile-v4.jsonl `
  --manifest eval/flask-graph-v4-scope-v2-manifest.json `
  --output data/v4-graph-rerun.json
```

脚本检查题集与实现 hash；代码变化后应建立新的实验清单并解释变更，不能覆盖冻结记录。

## 确定性验证与真实增量

最终全量 145 项测试通过，耗时 143.469 秒；包括 20 项图专项、2 项新增 API 测试和 V3 的 123 项回归。覆盖迁移、source span/符号校验、版本隔离、删除子图、分支移动、别名/作用域、增量重连、失败回滚与 Agent 预算。`compileall` 与 `git diff --check` 通过。

真实 Flask 先索引第一父提交 `329c32b916938d33fec41f40eb7ed854bf0b3e2b`，再索引 head：复用 235 个文件的语法事实，重新提取 1 个文件。未变化文件的引用仍在 head 重新连边；这些文件计数包含不需要 AST 的 inventory 文件，不等于解析了 236 个 Python 文件。

两跳样例 `eval/flask-graph-v4-sample.json` 使用独立 `data/v4-smoke-index`，返回 40 个节点、68 条边、40 条源码证据并显式标记截断。样例 SHA-256 为 `d1a377639d46d12eedc7e051ce1a53a964a2ba15806f203d1d93eb84b3e80da9`。样例不复制源码正文，全部引用属于所选 head。样例索引独立于 benchmark，避免新增父 snapshot 改变 FTS 统计。

安装包验证的最终状态见 [进度与交接](progress.md)。V5 完整工作台、V6 部署及真实模型质量仍不属于本次交付。本轮只在本机 Windows/Python 3.12 运行，未触发远程 CI。

最终 wheel SHA-256 为 `538bb09d429e96f8527a1d3c68f77bab8e4545ab57ac907efb25b11c0b4af62a`，已在新建 `data/v4-acceptance-venv` 离线安装。`python -I` 确认从安装目录加载；doctor、历史版本图查询、直接控制台 graph 问答和 Agent 工作进程均通过。包版本仍为 4.1.0，当前 dist 已替换历史产物，重复安装需 `--force-reinstall`。
