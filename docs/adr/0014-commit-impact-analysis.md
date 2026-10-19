# ADR 0014：V3.3 两 commit 变更影响分析

## 状态

已接受，适用于 V3.3.0。

## 背景

代码问答只能说明某个 snapshot 中有什么。面试和日常 review 还需要知道一次 commit 改了哪些文件和 symbol、是否能找到相关测试/文档，以及哪些风险只是推断。影响分析必须绑定 base/head 版本，不能把工作树或模型文本当作事实。

## 决策

1. 新增 `impact --repository <path> --base <ref> --head <ref>`，只接受本地可解析 commit；base 和 head 分别建立或复用 exact snapshot。
2. Git 层使用固定只读命令读取 `--name-status` 和零上下文 diff hunks，设置输出上限，不 checkout、不执行目标代码、不下载 objects；rename 当前用 `--no-renames` 表示为删除加新增。
3. 对受支持 Python 文件，使用 base/head snapshot 的 AST symbol 范围与 diff hunk 关联 added/removed/modified symbol；Markdown、测试、配置按路径分类。
4. 先用确定性规则生成 changed_files、related_tests、related_docs、risks、suggested_tests、unknowns 和 canonical evidence。风险与建议测试明确使用 `inference: true`。
5. 可选 provider 最多调用一次，只接收 evidence context，复用 `repolens.answer.v1` citation contract；模型结果作为 `model_answer` 附加层，不能覆盖 deterministic report。

## 后果

- 不需要 API Key 也能产出可复现的 impact 报告，DeepSeek 只用于补充自然语言摘要。
- 删除文件可以引用 base evidence，当前文件和相关测试/文档使用 head evidence；报告同时保留两个 snapshot ID。
- 当前实现不是调用图、历史原因分析或真实风险召回评测；跨语言 symbol、rename 识别和历史 investigation 留给后续版本。
