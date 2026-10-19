# ADR 0010：增加自动 ask 单轮工作流

## 状态

已接受，适用于 V2.3.0。

## 背景

底层 `answer` 命令要求用户先手动索引仓库、复制 snapshot ID 并选择 provider。这个入口适合调试和可复现实验，但不适合作为日常的“输入一个问题直接问代码”体验。

## 决策

1. 增加 `ask <question>` 命令，`--repository` 默认为当前目录，`--ref` 默认为 `HEAD`。
2. `ask` 自动创建或刷新当前 commit 的本地索引，然后使用生成的精确 snapshot ID 调用既有回答 pipeline。
3. `ask` 默认使用 DeepSeek，默认输出预算为 1024 token；`--provider mock` 保留为离线验证入口。
4. 输出继续使用既有 `answer`、`context`、`telemetry` 契约，并增加 `workflow` 元数据记录仓库、ref、commit、snapshot 和索引统计。
5. V2.3 的 `ask` 只做一次检索和一次生成，不自动执行目标仓库代码，不执行任意工具调用，也不保存多轮会话。

## 后果

- 用户可以用一个命令完成从仓库到回答的单轮闭环，同时保留底层 `answer` 作为可复现调试入口。
- 每次 ask 仍然绑定明确 commit，回答不会脱离 snapshot 证据边界。
- 多轮记忆、证据不足时的追加搜索和工具编排需要下一步单独设计和评测，不能把当前工作流称为完整 Agent。
