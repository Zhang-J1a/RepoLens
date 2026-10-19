# ADR 0018：V1 的 snapshot 绑定 Git 历史索引

## 背景

初始路线图要求 V1 同时保存代码、文档、测试和 Git 历史。此前 RepoLens 只把当前 commit 元数据保存到 snapshot，无法按 commit message、作者或历史提交检索。

## 决策

1. 对选定 snapshot，读取本地 Git 中从该 commit 可达的提交历史，最多保存 5,000 条提交。
2. 每条历史记录保存完整 commit SHA、父提交、作者、UTC 时间和 commit message，并写入独立的 `history_commits`/`history_fts` 表。
3. `search_history` 只在请求的 snapshot 内检索，历史记录不是当前源码 evidence，不混入代码 FTS 或向量表。
4. Git history 读取使用有界、只读命令；不 checkout、不执行目标代码、不修改目标仓库、不联网获取对象。
5. schema 升为 3，`INDEX_POLICY` 同时包含 `history-v1`。旧 schema 的向量表可迁移，但新策略 snapshot 会重新建立并写入历史。
6. snapshot stats 保存包含选定 commit 的本地 branch 名称；branch 仅作为当时的本地元数据，检索身份仍由完整 commit SHA 决定。

## 边界

- 5,000 条是资源上限，不代表仓库完整历史；超过上限的仓库需要后续分页或按时间范围索引设计。
- 历史检索结果提供 commit locator 和 message，不伪装成带文件行号的代码 evidence。
- 当前只验证 Python/Markdown 代码索引和本地 Git history；多语言 parser 和跨仓库质量仍需独立评测。
