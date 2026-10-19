# ADR 0020：V2 影响报告结构化质量评测

## 决策

1. 新增 `evaluate-impact`，读取 reviewed JSON gold set，对固定 base/head commit 运行 provider-free impact pipeline。
2. 分别计算 changed files、changed symbols、related tests、related docs 和 risk severities 的 precision/recall/F1；不把不同维度合并成一个掩盖缺陷的总分。
3. 同时验证报告 schema、base/head snapshot binding、evidence canonical validity 和内部 reference binding。
4. `partial` 是有效报告状态，不是运行失败；它表示系统发现了证据不足或解析不完整，并且必须在评测结果中单独可见。

## 证据边界

当前 gold set 覆盖 10 个固定 Flask commit，适合评估结构化报告契约和静态证据绑定。它不测动态调用、跨语言调用或生产风险召回；这些能力需要独立标注和后续图谱/Agent 阶段。
