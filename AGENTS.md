# RepoLens 协作约定

继续工作前先阅读本文件与 `docs/progress.md`。修改行为前，再阅读架构、开发约定和相关测试。

## 产品边界

- 构建与仓库无关、证据优先的代码 RAG 项目，适合作为个人面试作品集。优先展示可验证行为，不堆叠基础设施。
- 上层工作区中的 `all-in-rag` 和 `AgentGuide` 仅供个人学习参考，不得修改、索引或用于评测。
- Flask 是首个评测目标，不是产品依赖。评测必须固定在 `docs/target-repositories.md` 的确切 commit。
- 目标仓库是只读输入。索引期间不得执行其代码、安装依赖、跟随 symlink 或联网获取 Git objects。
- 索引位于目标仓库之外。不得提交密钥、下载的仓库、数据库或复制的上游源码。

## 协作与交接

- 使用中文沟通；编辑前说明范围和重要取舍。项目文档以中文为主，保留技术标识和命令。
- 按可运行的小里程碑推进。重大范围/provider 选择与用户确认，不对每个实现细节打断确认。
- 里程碑结束后更新 `docs/progress.md`，记录行为、确切验证命令与结果、限制和下一步。
- 长期决策记入 ADR，不只留在聊天中。不得将合成测试或 smoke test 当作真实检索质量证据。
- 除非用户明确授权，不使用 subagent。
- 用户未要求时，不 commit 或 push；保留已有未提交改动。

## 验证

初期支持 Python 3.12+，运行时仅标准库，测试使用 `unittest`：

~~~powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
~~~

测试必须离线并使用临时 Git 仓库。真实仓库 smoke/benchmark 与确定性回归测试分开报告。
