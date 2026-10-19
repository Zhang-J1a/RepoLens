# ADR 0023：V5 完整 Web 分析工作台

日期：2026-10-19。范围以原始路线图第 9 节为准。

## 决策

- `apps/web` 使用 React、TypeScript、Vite、TanStack Query、React Router 和 Tailwind；Monaco 提供只读代码/diff，React Flow 提供关系图，Recharts 展示真实评测数据。
- FastAPI/Pydantic 是 `web` 可选依赖。CLI、索引、检索与现有标准库 HTTP API 继续独立可用；工作台通过相同的 WebOperations 调用既有流水线，不重新实现分析逻辑。
- 本地服务只绑定 loopback。任务、结果、Trace 和 Key 位于进程内；任务有容量上限，SSE 支持事件序号与断线补读。任务输入不持久化。源码仅从指定 snapshot 的索引读取。
- 前端路由覆盖仓库、变更、图、问答、Trace、评测。空状态、错误态、加载态和窄屏必须验证。
- PR diff 只接收粘贴的 unified diff，并校验其变更内容对应用户指定的本地 base/head；不访问远程 PR、不应用 patch，不将上传文本当作已提交证据。
- 内置合成 Demo 创建独立的受管仓库，不读取或修改学习参考仓库。Demo 只用于交互/契约，不用于声称真实模型质量。
- 评测展示已有冻结结果与配置；未测量的引用支持度、回答准确率显示“未评测”，不从引用结构合法推算质量。

## 验收顺序

1. API、仓库管理、只读证据/diff、异步任务/SSE、OpenAPI 与类型。
2. 六页面及报告导出、代码/图/Trace 交互。
3. 离线 API/核心回归、前端类型/构建/浏览器端到端、桌面/窄屏检查。
4. Demo、双击入口、使用说明、安装包与逐项路线图核对。

V6 的容器部署、统一系统监控和跨模型质量评测不在本次交付声明中。
