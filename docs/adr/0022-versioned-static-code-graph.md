# ADR 0022：持久化静态代码图与版本隔离

状态：已采纳。对应原始路线图 V4；沿用标准库和 SQLite，不引入专用图数据库。

## 数据与迁移

- SQLite schema 3 升至 4，增加 `graph_builds`、`graph_nodes`、`graph_edges` 和 `graph_file_facts`。节点与边都绑定 snapshot；边的两个端点使用复合外键强制属于同一 snapshot。
- 图策略独立为 `python-import-scope-graph-v2`。v2 修复方法裸名称不能沿类命名空间查找、嵌套同名 receiver 不能沿用外层 self 的边界；v1 的实验记录保留。源码切分规则没有改变，因此保留原有 INDEX_POLICY 和 evidence ID，不以换包版本代替路线图验收。
- 新 snapshot 的源码、向量、图谱在同一 SQLite 事务内保存；图构建失败时回滚整个替换，保留上一个完整版本。旧 schema 在 writable ingest 时迁移；已有 snapshot 的图按需要构建，不在只读查询时偷偷修改数据库。
- 父 snapshot 中相同路径/blob 的语法事实可以复用。所有引用在当前 snapshot 重新连边，避免被调用者改变或删除后保留旧目标。这是增量语法解析加当前版本完整连边，不声称只更新了变化边。

## 关系语义

节点契约包括 repository、branch、commit、file、module、function、class、interface、test、configuration、document。Python `Protocol/ABC` 的显式基类可标记接口；其他语言未增加 parser。未索引文本的配置文件仍可作为带 Git blob 来源的文件/配置节点；不会编造其行号或配置项。

边契约包括 contains、defines、calls、imports、implements、tests、documents、modifies、depends_on、replaces。当前构建器只输出有语法/对象证据的关系：

- 调用通过当前模块、词法作用域、显式导入/别名/重导出和单继承方法查找解析。参数遮蔽、无法唯一确定的同名定义、未知接收者和动态调用不做全局末尾名称猜测。
- 类继承产生 implements；test 文件中已解析的调用同时产生 tests。这表示静态测试引用，不表示执行成功或测试覆盖率。
- Markdown 中出现可唯一定位的完整符号名时产生 documents，标为 inference；不把词法提及当成语义证明。
- 配置字面 key 访问产生 configuration 节点和 depends_on。modifies 来自本地 Git diff；父提交对象不可用时记录 changes unavailable，不联网获取。
- replaces 仅保留在 schema 中；没有可信的显式替代/版本映射时不自动生成。重命名、相似名字或委托调用本身不能证明 API 替代关系。

每条节点/边携带 snapshot、完整 commit、可选 path/blob/行号和 evidence ID。查询再次校验 provenance、source span 和符号定义。仓库、分支、commit 和 unsupported 文件节点以 Git 元数据为来源，不虚构源码 excerpt。

## 查询与检索

- 子图支持 symbol（可加 path 消歧）、path、commit 或宿主 seed IDs，最多两跳，节点/边各有硬上限，截断显式报告。commit 种子保守覆盖修改后仍存在文件的符号；删除文件在独立 base 子图分析，不混入 head 证据。
- branch/ref 在任务开始解析为完整 SHA，然后使用对应 snapshot。分支移动不改变旧图。`impact --with-graph` 的种子来自实际 base/head diff，不能错误地使用 head 的第一父提交代替用户指定范围。
- `graph` 检索固定纯向量候选池为 100，以精确符号或前五个向量命中作为种子，沿 calls/implements/tests/documents/depends_on 扩展两跳；按固定 RRF 风格权重合并向量和邻域证据，不按 gold 修改结果。路径过滤在最终证据中同样生效。
- graph review priority 仅用于候选检查排序；原有 low/medium/high/blocking 风险 rubric 不因图邻居数量自动升级。
- 提供 CLI、`POST /api/graph` 和 `POST /api/search`；原有问答可选 `--retrieval graph`。V3 的关系工具复用图查询；通用 `search_code` 继续默认 hybrid，可显式选择 graph，原因是补充 20 题中 graph 存在回退。权限仍由宿主控制。完整交互式关系图工作台留在 V5。

## 验证要求

使用临时 Git 仓库验证别名、继承、同名歧义、参数遮蔽、删除、分支移动、跨 snapshot seed 拒绝、增量缓存、事务回滚和损坏引用。真实 Flask 比较使用固定 commit、冻结数据与实现 hash，分别报告纯向量、hybrid、graph 的 Recall/MRR/nDCG 和耗时；必须保留回退项。不把 authored 同仓库任务称为外部盲评，也不将静态边称为动态执行图。
