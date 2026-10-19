# ADR 0013：V3.2 有界追加检索

## 状态

已接受，适用于 V3.2.0 及后续兼容实现。

## 背景

单次 lexical retrieval 可能先找到一个相关但不足以回答问题的 evidence。无限循环检索或开放任意工具调用会让成本、延迟、权限和上下文都失去边界，因此需要一个可以离线测试的最小 Agent 行为。

## 决策

1. `QuestionAnswerPipeline` 增加 `max_follow_up_searches`，只允许 `0..3` 次追加检索；`answer` 默认 0，`ask/chat` 默认 1。
2. 首轮没有可打包 evidence，或 provider 返回合法 `abstained` 时，才尝试下一轮；provider 返回 `answered` 后立即停止。
3. 追加 query 只能来自当前问题、历史 user 消息中的 bounded identifier terms，以及已有结果的 symbol/path；query 去重并记录在 `retrieval_queries`。
4. 每轮最多调用一次 provider；所有轮次的 evidence 都来自同一个精确 snapshot，且每次模型输出都重新经过 citation validator。
5. telemetry 记录 retrieval rounds、generation rounds 和 follow-up searches，不记录 prompt、源码或 API key。

## 后果

- 证据不足时可以有限扩大召回范围，仍能测量 provider 调用上限和延迟边界。
- 追加检索不是通用工具 Agent；它不能执行代码、修改仓库、联网获取 Git objects 或调用 allow-list 之外的工具。
- 增加的 retrieval 可能带来重复 evidence 或无收益 query，因此必须通过固定测试和 telemetry 审阅，而不是只看一次 smoke test。
