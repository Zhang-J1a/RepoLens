# ADR 0019：V2 结构化影响报告增强

## 背景

已有两 commit impact 能力可以列出变更文件、Python symbol、测试、文档和规则风险，但还没有把 snapshot history、配置证据、Markdown 输出和完整风险等级纳入稳定报告契约。

## 决策

1. impact report schema 升为 `repolens.impact.v2`，增加 `related_history` 和 `related_configuration`，保留 base/head snapshot 和 canonical evidence。
2. 风险严重级别固定为 `low`、`medium`、`high`、`blocking`；所有规则风险仍标记 `inference: true`，规则不会读取模型置信度。
3. Markdown 只是同一结构化 report envelope 的渲染，不重新推断事实；CLI 通过 `impact --format json|markdown` 输出。
4. 每个真实样例使用本地完整 commit 和第一父提交，样例摘要不保存上游源码正文。

## 当前边界

- `related_history` 当前检索 bounded commit message、作者和路径/symbol 词，不能替代设计理由抽取。
- 当前调用方/被调用方只使用 Python AST 的直接静态调用，并要求目标解析到当前 snapshot 的 indexed symbol；动态调用、反射、装饰器注册、跨语言依赖子图和历史版本图属于后续代码图谱/Agent 能力。
- 10 个 Flask commit 样例用于验证报告契约和异常处理，不代表跨仓库影响风险召回率。
