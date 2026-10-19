# ADR 0011：复用精确 snapshot，避免 ask 重复索引

## 状态

已接受，适用于 V2.4.0。

## 背景

`ask` 需要自动完成索引，但同一个仓库和 commit 的内容不会因为重复提问而变化。每次都重新读取 Git blobs、解析源码和重建 FTS 索引会增加等待，也掩盖了 snapshot 身份本来可以确定的事实。

## 决策

1. 根据 canonical repository root、commit SHA 和 `INDEX_POLICY` 计算确定性的 snapshot ID。
2. `ask` 在打开索引前验证数据目录仍位于目标仓库和 Git 目录之外；已有数据库若 schema 不兼容则失败，不静默重建。
3. 数据库中存在精确 snapshot ID 时直接复用；不存在时才执行完整 `ingest`。
4. 输出 `workflow.index_action`，值为 `created` 或 `reused`，让用户可以确认本次是否重新索引。
5. 只要 commit、仓库身份或解析/index policy 变化，snapshot ID 就变化，不跨版本复用证据。

## 后果

- 同一版本的连续提问跳过 blob 读取和解析，保留原有 snapshot 隔离和 evidence 校验。
- 索引数据库仍是本地、可重建存储，不需要新增缓存服务或运行时依赖。
- `ask` 仍然是单轮工作流；多轮记忆和追加检索留给 V3。
