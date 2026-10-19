# V4：代码关系图与版本感知检索

V4 按原始路线图补齐持久化图谱、版本选择、有界子图、检索扩展及可重复对比。包版本仍为 4.1.0；完整 React 分析工作台属于 V5。

## 图数据

图与源码索引同存在外置 SQLite 中，使用 schema 4。新导入时自动构建；旧索引先运行一次 `ingest` 完成迁移/选定 snapshot 的图构建，旧版程序不能读取 schema 4，需保留原数据备份或使用新数据目录进行对比。

节点和边返回 `repolens.graph.v1` JSON。每个节点/边都有 ID、snapshot、种类、来源；代码位置带 path、symbol、行号或 evidence ID。图边和端点同属一个 snapshot；source-span 与符号定位可再次验证。元数据节点以 Git commit/blob 为来源，不提供虚构的源码行。

Python 支持静态定义、导入别名/重导出、作用域、唯一可解析调用与单继承方法。测试边代表静态引用；Markdown 的显式完整符号名提及标为 inference。动态接收者、复杂多继承分派、反射、外部依赖和跨语言解析不在保证范围。`replaces` 类型预留，有证据之前不自动生成替代断言。

## CLI

在 `D:\RAG\RepoLens` 使用源码时设置 `$env:PYTHONPATH = "src"`，已安装包则直接使用 `repolens`。

```powershell
$env:PYTHONPATH = "src"
python -m repolens graph `
  --repository D:\RAG\RepoLens\data\repositories\flask `
  --ref d086db856be187255b8ec61ef409357393020f32 `
  --symbol Flask.handle_http_exception --hops 2 `
  --data-dir D:\RAG\RepoLens\data\v4-flask-index
```

选择 `--path src/flask/app.py` 可以查看文件邻域；同名 symbol 可同时加 `--path` 消歧。`--commit` 以所选 commit 的修改文件符号为种子。最多两跳，默认 100 个节点、200 条边；使用 `--max-nodes` / `--max-edges` 调整，超过上限返回 `truncated`。没有可用父提交对象时不会联网获取，commit changes 状态会说明覆盖缺口。

删除文件只在独立 `base_graph` 返回旧版本关系；head 仍保持自身的节点和引用。比较任意两个版本可以使用：

```powershell
python -m repolens impact `
  --repository D:\RAG\RepoLens\data\repositories\flask `
  --base 329c32b916938d33fec41f40eb7ed854bf0b3e2b `
  --head d086db856be187255b8ec61ef409357393020f32 `
  --with-graph --provider mock --data-dir D:\RAG\RepoLens\data\v4-flask-index
```

返回原 V2 报告与 `graph`；删除范围另有 `graph_base`。`graph_review_priority` 辅助检查顺序，不改变规则风险严重级别，不代表概率或运行时覆盖率。

问答使用图增强：

```powershell
python -m repolens ask "Flask.handle_http_exception 调用的错误处理器查找逻辑在哪里？" `
  --repository D:\RAG\RepoLens\data\repositories\flask `
  --ref d086db856be187255b8ec61ef409357393020f32 `
  --retrieval graph --provider mock --data-dir D:\RAG\RepoLens\data\v4-flask-index
```

Mock 只验证引用流程；真实模型使用 `--provider deepseek` 和已有环境变量，不在参数中提供密钥。`search` / `evaluate` 也支持 `--retrieval graph`。branch、tag 和 commit ref 每次先固定为 SHA，不会在一步分析中跟随分支后续移动。

## 本地 API

`POST /api/graph`：

```json
{
  "repository": "D:\\RAG\\RepoLens\\data\\repositories\\flask",
  "ref": "d086db856be187255b8ec61ef409357393020f32",
  "symbol": "Flask.handle_http_exception",
  "hops": 2,
  "max_nodes": 100,
  "max_edges": 200
}
```

`POST /api/search` 同样选择 repository/ref，另外提供 `query`、`retrieval: "graph"`、`limit` 和可选 `path_prefix`。响应返回固定 snapshot/commit 和 canonical evidence；`POST /api/ask` 可以传 `retrieval: "graph"`。`POST /api/impact` 可传 `with_graph: true`。API 和 CLI 复用相同查询逻辑。

V3 Agent 的 `find_references` 和 `build_dependency_subgraph` 复用持久化图；后者可请求 `hops: 1|2`，返回节点和边，仍受工具结果、任务步数和总超时限制。`search_code` 继续默认 hybrid，可请求 `retrieval: "graph"` 进行关系扩展。图谱交互页面现已在 [Web 工作台](v5-workbench.md) 实现。

## 评测

独立于单元测试，`scripts/graph_benchmark.py` 在第一次检索前冻结 dataset 和实现 hash，再对相同 snapshot 比较 vector/hybrid/graph，报告全部单题差值。使用说明、实际指标与限制见本轮评测记录；不能把构建成功或合成 fixture 当作跨仓库质量收益。

实际对比、重现命令与回退样例见 [V4 图谱评测](evaluation-graph-v4.md)。跨文件 10 题 R@10 为 vector 0.80、hybrid 0.85、graph 0.95；原有 20 题中 graph R@10 为 0.50，低于 hybrid 0.6083，因此没有替换通用默认检索。
