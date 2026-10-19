# ADR 0017：按路线图对齐 V1 向量与增量检索

## 背景

当前包版本经历了早期的 V1 到 V4.1 功能叠加，但路线图中的阶段职责已经错位。已有 FTS5/BM25 和 Web UI，而 V1 要求的可替换 Embedding、向量检索、混合检索和增量索引仍不完整。本决策把后续交付重新按路线图能力划分；包版本继续独立记录发布版本，不用版本号掩盖尚未完成的路线图阶段。

## 决策

1. `EmbeddingProvider` 作为检索层的窄接口，provider 负责拟合模型、编码文本和导出可持久化模型描述。
2. 首个 provider 使用标准库实现的本地 TF-IDF 稀疏向量。它是离线、可复现的向量检索基线，不宣称具备外部语义模型的理解能力。
3. 每个 snapshot 独立保存向量模型和 chunk 向量，查询只读取选定 snapshot，避免跨版本泄漏和全库 TF-IDF 统计污染。
4. `IndexStore` 保留 FTS5/BM25 关键词检索，并新增 `search_vector` 与加权 RRF 的 `search_hybrid`。关键词、向量和混合结果都返回可解释的分数或排名元数据。
5. 新 commit 如果其父 snapshot 已存在，按 blob、路径和语言复用未变化文件的解析结果；新增或变化文件才重新读取和解析。缺少父 snapshot 时回退完整索引。
6. schema 从 1 升到 2，`INDEX_POLICY` 同时升级为包含向量策略的版本标识。旧的本地索引在下一次可写 ingest 时创建向量表并回填本地向量；新 ingest 不会把旧策略 snapshot 当作新策略的精确复用来源。不兼容的未知 schema 仍拒绝打开。

## 取舍与边界

- TF-IDF 不能替代 DeepSeek 或其他 embedding API；接入外部 provider 仍需单独的隐私、延迟和质量评测。
- 增量索引复用的是已解析的 committed blob，不读取 dirty/untracked 文件，不执行目标仓库代码，也不下载 Git 对象。
- 当前语言覆盖仍是 Python AST、Markdown 和已有的有限文本 fallback；Tree-sitter、多语言调用关系和代码图谱属于路线图后续阶段。
- 评测需要分别报告 keyword、vector 和 hybrid 的指标，不能用混合结果掩盖单一路径的缺陷。
