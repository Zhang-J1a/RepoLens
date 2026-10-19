# ADR 0021：受控 Agent、进程隔离和 Trace

状态：已采纳。对应原始路线图 V3，延续 V2 的只读证据边界。

## 决策

- 新增 `src/repolens/agent/`，使用显式状态机：prepare、baseline、tool、agent_plan、agent_answer、answer_validation、stop。不引入 LangGraph；当前顺序状态、固定工具和单任务上下文不需要额外运行依赖。
- 工具集合固定为路线图列出的八项。工具名称、参数 schema、仓库 root 和 base/head snapshot 由宿主控制。模型不能选择其他仓库、commit、shell、写入权限或 URL。
- `get_commit_diff` 只接受任务已绑定的 base/head。代码与文件上下文只从索引读取，引用再次通过 source-span 校验。history 返回可达提交；它是检索线索，不冒充 `answer.v1` 的代码引用。
- 复用 vendor-neutral `ProviderRequest/ProviderResponse`。DeepSeek 使用同一个适配层请求 JSON 工具决策，`temperature=0`；每个决策只允许一个工具或 finish。离线 Mock 使用固定规则规划，不能作为真实模型多步推理质量证据。
- 工具、索引准备、规则报告和 provider 在标准库 `multiprocessing` 的 spawn 进程中执行。任务共享 monotonic deadline；超时终止并回收工作进程。每个任务只保留一个模型进程，保证脚本 provider 的内部状态能够跨步骤保留。
- 限制工具步数、模型调用数、单次和累计返回条数、上下文、输出、累计 token 预留及总时间。失败调用消耗步数；重复成功或失败调用签名不再执行。连续两次工具失败停止，底层 DeepSeek 临时故障重试仍有上限。Agent CLI/API 默认关闭 HTTP 重试；显式启用时，累计 token 为所有可能尝试预留。
- token 预留包含完整问题、上下文、工具目录、schema、输出 cap 和固定系统开销。它是确定性的估算，并非供应商 tokenizer、计费承诺或绝对上下文长度保证。
- commit 范围任务先取得 provider-free V2 规则报告。模型不可用、超时、非法 JSON/决策、伪造引用或预算不足时保留已取得证据与规则报告，返回 `degraded` 和分类 stop reason。准备/规则阶段本身超时时，尚未生成的报告为 null。
- 不将原始源码、prompt、原始模型文本或 provider 异常写入 Trace。Trace 包含 task/trace ID、宿主参数、证据定位、工具结果元数据、已验证决策、模型输出 hash、usage、耗时和分类错误；无效决策仅记 hash。常见密钥形式额外脱敏。结果在内存和响应中返回，不自动写入磁盘。

## 边界

`find_references/build_dependency_subgraph` 复用有限 Python AST 名称匹配，只返回一跳候选并标记 inference。对象类型、同名歧义、别名、动态调用、跨语言关系没有解决；V4 的持久化关系图、两跳扩展与图增强效果评测未提前宣布完成。

已安装模型适配器需要可被 spawn 序列化，标准 DeepSeek/Mock 支持。自定义 provider 应使用模块顶层类和可序列化配置，不在 provider 中保存打开的连接或 lambda。不能把任意不可信 Python 插件放进进程后视作操作系统沙箱：白名单保护的是模型决策，运行的适配器属于可信项目代码。

固定模型名、参数、snapshot、工具和检索配置能复现实验设置；远程服务不保证逐字相同输出。离线规则规划用于验证确定性行为。完整 UI、Trace 浏览工作台与部署仍分别属于 V5/V6。
