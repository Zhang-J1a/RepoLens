# 维护性审查与本轮取舍

日期：2026-10-20。用户明确暂缓 M4 选仓，先进行文档收口、M9 维护性与关键测试，再准备模型评测及只读 MCP。不改变 M6/M8 对独立评测基线的要求。

## 测量与职责

`python scripts/project_audit.py --check-links` 用标准库 AST 汇总模块行数、函数跨度、静态内部依赖和直接导入该模块的测试文件，同时检查常见 Markdown 本地链接是否存在。它不运行被分析仓库，不访问网络。静态测试导入不是动态覆盖率，函数跨度不是复杂度，不能据此给出代码质量百分比。

| 模块 | 调整前行数 | 判断与处理 |
|---|---:|---|
| `webapp.py` | 855 | 包含兼容 HTML、HTTP handler 与共享 WebOperations；workbench 仍复用操作层。保留兼容入口，不在本轮大规模迁移 |
| `index.py` | 644 | schema、事务写入、版本过滤与检索高度关联，已有索引/图/评测测试；不为缩短文件拆开事务边界 |
| `impact.py` | 600 | 纯 Markdown 渲染与 Git/索引/推断职责可分离；提取到 `impact_rendering.py`，原导入接口保留 |
| `cli.py` | 558 | parser 和 main 分别为 156/155 行；选项与命令分支仍可追踪，本轮避免拆分后多处同步参数 |
| `styles.css` | 1664 | 当前共享六页面样式；未发现仅凭行数足以支持重构的证据，先保留已验收桌面/窄屏行为 |

渲染提取保持函数源码逐字一致，并使用既有 CLI/Markdown 集成测试检查兼容。提取后的 `impact.py` 为 522 行；减少行数只是结果，职责隔离才是目的。

## 关键边界测试

已有确定性测试覆盖 dirty/untracked 隔离、跨仓库/snapshot、非法路径、损坏 evidence、图事务回滚、模型超时回收、预算和引用失败关闭。本轮补充两个实际 Git fixture 场景：

- 为临时仓库配置会写 marker 的 post-checkout hook 和 smudge filter；索引后必须能检索 committed 源码且 marker 不存在，工作树状态不变。
- 临时仓库设置 Git replace ref；旧 SHA 的索引仍返回旧源码和可达历史，不允许被替换对象带入新版本。

这些是行为回归测试，不能当成所有 Git 安全风险已被消除。新增 pytest/coverage/Ruff/Mypy 等依赖仍未获单独授权，本轮继续使用标准库；类型检查的工具化门禁尚未完成，不称 M9 全项交付。

CI 后续暴露兼容 HTTP 的断连路径：响应写入已关闭连接时不能再尝试发送 500。JSON/HTML 发送步骤统一并覆盖三种 ConnectionError 在响应头/正文阶段的 12 个子场景。版本绑定测试在已准备的 snapshot 上通过 HTTP 验证精确版本及复用，保持客户端超时不变；另有冷启动图问答明确断言 created。测试准备和索引性能评测分别处理，不能将预建索引称为性能提升。

## 文档与 CI

README 改为项目定位、实际截图、三条命令 Docker Demo、当前检索对照及限制，操作细节迁入 `docs/usage.md`。部署与 V6 验收同步实际全绿运行，保留本机未安装 Docker 和真实模型未评测的限制。CI 加入本地文档链接检查，不联网检查徽章或远端 URL，不解析完整 CommonMark，也不校验页面锚点。

完整验证命令与结果继续记录在 `docs/progress.md`；历史题集、gold、policy 清单与默认 hybrid 均保留。
