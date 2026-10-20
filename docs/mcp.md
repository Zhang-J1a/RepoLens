# 只读 MCP / Agent Context

提供标准库实现的本地 stdio MCP 最小工具服务，协议版本固定为 `2025-06-18`。复用现有 ControlledAgent 工具校验、snapshot 绑定、索引证据验证和 spawn 超时；不增加 SDK、模型或网络依赖。

已用独立子进程客户端验证 initialize、工具发现和源码证据调用。尚未对第三方桌面客户端或官方 SDK 做互操作验收，不声明完整 MCP 功能覆盖。

## 准备与启动

先用 RepoLens 正常 ingest 获得精确 snapshot ID。MCP 服务只读取已存在索引，启动不会自动 ingest、迁移数据库或下载仓库。

```powershell
.\.venv\Scripts\python.exe -m repolens.mcp_server --repository <local-git-root> --index <index-directory> --snapshot <snapshot-id>
```

安装后的等价入口为 `repolens-mcp`。需要 commit diff 时，由宿主另传 `--base-snapshot <base-snapshot-id>`；base/head 必须属于同一规范 Git root。客户端工具参数不能覆盖 repository、snapshot、base/head 或索引目录。

客户端通用配置示意，需替换为自己的真实绝对路径与 snapshot：

```json
{
  "mcpServers": {
    "repolens": {
      "command": "C:/path/to/RepoLens/.venv/Scripts/python.exe",
      "args": [
        "-m", "repolens.mcp_server",
        "--repository", "C:/path/to/your-repository",
        "--index", "C:/path/to/repolens-index",
        "--snapshot", "snapshot-id-from-ingest"
      ]
    }
  }
}
```

不同客户端的配置文件位置和名称可能不同，本示意不代表已为某个具体产品完成安装。

## 工具

| 工具 | 内容 |
|---|---|
| `search_code` | 默认 hybrid，可显式选择 graph |
| `find_symbol` | 固定 snapshot 的 qualified/leaf symbol |
| `find_references` | 有 provenance 的静态调用邻域 |
| `get_file_context` | 已提交文件行范围相交的完整证据 chunks |
| `search_history` | 当前 snapshot 可达的已索引 commit message，不当作代码引用 |
| `get_commit_diff` | 宿主固定 base/head 的路径与零上下文 hunks |
| `build_dependency_subgraph` | 最多两跳的静态子图 |
| `get_evidence` | 仅在宿主选定的 head/base snapshot 中解析 evidence ID |

返回内容附带固定版本 binding；源码 evidence 包含 commit、snapshot、path、symbol、行号及 evidence ID。Git/history 元数据有自己的来源，不能虚构不存在的源码范围。`get_evidence` 会再次经过 `IndexStore.evidence` 的逐行校验。

## 约束

- 输入 schema 为封闭对象；不存在 shell、写文件、安装、checkout、模型调用或任意 URL 工具。
- 默认会话最多 8 次工具尝试、每次最多 8 项、累计最多 64 项；非法/失败调用消耗步数，重复调用拒绝执行。
- 结果在工作进程内限制为 128 KiB；累计结果最多 1 MiB。超限失败关闭，不静默截断成貌似完整的证据。
- 会话自启动起默认 120 秒；单次工具进程最多 15 秒，超时终止并回收。`--timeout` 只由宿主配置，沿用 AgentBudget 的有界取值。
- stdio 输入每条最多 128 KiB、最多 256 条消息；stdout 只写单行 UTF-8 JSON-RPC。服务不持久化 prompt、源码、结果或日志。
- 支持 initialize、initialized notification、ping、tools/list 和 tools/call。版本不匹配时返回本服务支持的版本，由客户端决定是否继续。

当前同步处理请求，不支持 HTTP transport、resources/prompts、sampling、并发取消或动态工具列表。关闭 stdin 会结束会话；空闲/预算到期后重新建立会话，而不是扩大旧任务预算。目录只读边界不等于磁盘内容经过签名，其他本机进程仍可修改输入索引。

仓库正文是不可信数据；即使 README 要求忽略规则或执行命令，也不会改变宿主工具目录。外部客户端如果将返回源码交给远程模型，其数据发送和费用由该客户端另行配置；本服务自身不调用模型。

## 规范依据与验收

实现依据官方固定版本的 [stdio transport](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)、[lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle) 和 [tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)。不把这一版本描述为当前最新协议。

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -p test_mcp.py -v
```

测试包括八个工具的版本绑定、未来 evidence 和错误 root 拒绝、损坏证据、prompt injection、非法路径/额外权限、重复/预算/字节上限、握手与 malformed frame，以及实际 stdio 子进程。既有 Agent 测试另外验证 spawn 超时后无遗留进程；这些测试不能替代第三方客户端互操作或真实代码问答质量评测。
