# RepoLens V1 验收记录

## 交付结论

V1 对应 Python 包 `repolens==1.0.0`，完成本地索引、确定性检索、证据定位和离线评测闭环。安装包位于 `dist/repolens-1.0.0-py3-none-any.whl`。本次是本地交付，没有向 PyPI/GitHub 发布，也未创建 RepoLens Git commit。

完成条件是功能闭环、版本/证据边界正确、实验可复现、安装可用，以及如实报告检索质量；没有把尚未达到的自然语言检索质量冒充发布门槛通过。V1 是后续代码 RAG 的检索基础，完整生成式回答属于 V2。

## 验收项

| 验收项 | 状态与证据 |
|---|---|
| 授权本地仓库、固定 commit 索引 | 通过：Flask 重新索引到新目录；临时 Git 仓库覆盖多版本和 bare clone |
| 不执行目标代码、不修改目标工作树 | 通过：测试及 Taskboard 演示检查工作树、Git index 与证据 |
| snapshot 过滤、历史证据稳定 | 通过：dirty/untracked 隔离、多仓库身份、跨 snapshot evidence 拒绝 |
| 解析、跳过状态、事务重建 | 通过：Python AST、Markdown、编码、fallback、symlink/submodule、回滚测试 |
| 检索和证据边界 | 通过：固定 100 候选，limit 的排名前缀一致；拒绝损坏的空/逆序/越界证据 |
| 评测及同名 symbol 定位 | 通过：getter/setter 按具体包含范围验证；冻结基线保留 |
| 新验证数据 | 通过执行：20 题、28 locator，四类各五题，运行前冻结，未据结果调参 |
| 全量本地测试 | 56 项通过；`compileall` 通过 |
| 安装包 | wheel 离线构建并安装到干净 venv；`python -I` 确认从 site-packages 导入 |
| 用户演示 | 已安装包完成 `doctor/ingest/search/evidence/snapshots`，见 `eval/v1-demo.json` |
| CI | 已配置 Windows/Ubuntu、Python 3.12/3.13；尚未触发远程执行 |
| 中文交付文档 | README、架构、评测、验收、面试说明和交接记录已同步 |

## 修复与范围

- 返回条数为 5 时原候选池为 50，返回条数为 10 时为 100，可能让两者前五条不同。现在统一 100；权重及分词保持冻结，开发集 top-10 指标未变。
- symbol 名称可能因 property setter、overload 或嵌套定义重复。评测现在确认至少一个同名定义包含完整定位范围，不依赖 SQL 第一行。
- 源码范围验证增加 `1 <= start <= end <= source_line_count`，防止损坏索引中的空范围通过空字符串比较。
- 新增 `doctor`，检查 Python、Git 和 FTS5，可在没有数据库时定位环境问题。
- 包版本统一从 `repolens.__version__` 读取，避免包元数据与 CLI 各自维护不同版本。

## 留出验证集

`eval/flask-validation-manifest.json` 在首次检索前记录了题集和检索实现的 SHA-256。20 道新题的 gold symbol 与原开发集不重叠；同一验证集内部允许不同问题共用源码，因此统计仍可能相关。题目依据源代码编写，不是外部独立评审。

| 分类 | 题数 | Recall@5 | Recall@10 | MRR@10 | 去重证据单元 nDCG@10 |
|---|---:|---:|---:|---:|---:|
| 精确标识符 | 5 | 1.000 | 1.000 | 1.000 | 1.000 |
| 英文自然语言 | 5 | 0.400 | 0.600 | 0.333 | 0.397 |
| 纯中文自然语言 | 5 | 0.000 | 0.000 | 0.000 | 0.000 |
| 带标识符的多方法证据 | 5 | 0.800 | 1.000 | 0.867 | 0.819 |
| 题目宏平均 | 20 | 0.550 | 0.650 | 0.550 | 0.554 |

查询执行错误为零；纯中文查询返回空结果，反映 FTS5 无跨语言语义能力。数据集没有被改写以改善分数，也没有引入中文关键词到函数名的特例映射。用户使用 V1 时应带代码标识符或使用与源码一致的语言。

此次样本 P50 为约 3.79 ms、P95 约 5.98 ms，仅包含检索调用，不含建库、输入校验和进程启动。纯中文无候选查询降低了总体延迟；小样本和本机缓存影响明显，不作为吞吐量、生产 SLO 或跨版本加速证明。

## 复现实验

结果文件：

- `eval/flask-v1-ingestion.json`：从 commit objects 新建索引的统计。
- `eval/flask-v1-development.json`：30 题开发集，R@10 0.792。
- `eval/flask-v1-validation.json`：20 题冻结验证集，R@10 0.650。
- `eval/flask-validation-manifest.json`：数据与冻结实现的 hash。
- `eval/v1-demo.json`：合成 Taskboard 安装包演示结果，不是质量 benchmark。
- `eval/v1-acceptance.json`：最终安装包及交付文件摘要。

本地验证环境为 `data/v1-acceptance-venv`；可以直接运行：

~~~powershell
.\data\v1-acceptance-venv\Scripts\repolens.exe doctor
.\data\v1-acceptance-venv\Scripts\python.exe -I scripts/demo.py
$snapshot = (Get-Content eval/flask-v1-ingestion.json -Raw | ConvertFrom-Json).snapshot_id
.\data\v1-acceptance-venv\Scripts\repolens.exe evaluate eval/flask-validation.jsonl --snapshot $snapshot --data-dir data/v1-flask-index
~~~

构建与回归命令：

~~~powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m compileall -q src tests experiments scripts
python -m pip wheel . --no-deps --no-build-isolation --no-index --wheel-dir dist --disable-pip-version-check
~~~

本机离线构建使用 setuptools 81.0.0。其他机器若缺构建工具，直接安装已交付 wheel，或先准备 setuptools。索引必须位于目标仓库及其 Git 目录之外。若 Git 报 dubious ownership，应核实仓库所属账户；本轮以仓库所属用户只读重建索引，没有放宽全局 Git 信任配置。

## 明确限制与 V2 状态

只支持 commit 中的 Python/Markdown；任意仓库表示路径/身份通用，不表示所有语言或所有仓库都有相同质量。BM25 统计在同一数据库内共享；评测应固定索引集合。旧评分采用 symbol 相同且行范围相交即命中，不能替代语义充分性或答案正确率。验证集来自一个仓库，也没有生成式拒答评测。

V2.1-V2.3 已完成 provider 接口、证据上下文预算、结构化回答、citation 校验、无证据 abstention 和自动 `ask` 单轮工作流；V2.4 已接入 DeepSeek provider。真实 DeepSeek smoke test 已完成，但它只证明端到端契约可用，不代表生成质量评测。真实模型调用时才需要 API key，密钥不应进入源码、评测文件或 Git。
