# 首批评测仓库

以下仓库只作为真实评测输入，不是 RepoLens 的源码依赖或产品范围。用户使用 RepoLens 时，可以选择自己拥有或获授权读取的任意本地 Git 仓库。`all-in-rag` 和 `AgentGuide` 不是评测目标。

| 语言 | 仓库 | 许可证据 | 2026-10-17 观察到的 snapshot | 评测用途 |
|---|---|---|---|---|
| Python | `pallets/flask` | `pyproject.toml` 声明 BSD-3-Clause，存在 `LICENSE.txt` | `d086db856be187255b8ec61ef409357393020f32` | 主结构/检索 benchmark；有常规 package、测试、文档和历史 |
| TypeScript | `sindresorhus/is` | `package.json` 声明 MIT，存在 license 文件 | `e9c026c611c1160eaad50da00be4e676b626018f` | 后续用于验证第二语言 adapter |

## 使用规则

### M4 外部盲测目标待登记

当前已核验两个新候选，尚未满足 M4 的 3–5 个外部 Python 仓库要求。2026-10-20 用户确认：`AgentGuide` 和 `all-in-rag` 保留仅学习约定，不参与评测；允许公开最终选定仓库的名称、固定提交号和评测结果，不公开源码与本机路径。

| 仓库名称 | 本地 HEAD 完整 SHA（2026-10-20） | Git 中的 Python / Markdown / 常规测试文件数 | 许可证据 | M4 状态 |
|---|---|---|---|---|
| `HSI-SVM` | `616a42249247db5c7008e9825a6e2543b1400960` | 13 / 1 / 0 | 未发现 license/licence/copying/notice 文件；暂记 `NOASSERTION` | 用户授权的候选，尚待源码/领域/盲测资格审阅与题集冻结 |
| `Hyperspectral-classification-deeplearning` | `5b8641c2cf16f473393fc0cdd39475c3520c8e4d` | 6 / 2 / 0 | 未发现 license/licence/copying/notice 文件；暂记 `NOASSERTION` | 用户授权的候选，尚待源码/领域/盲测资格审阅与题集冻结 |
| `Book Manager V1` | `1e747f22254a254fbf90d1a2631165e79a675a4d` | 5 / 1 / 0 | 未发现 license/licence/copying/notice 文件；暂记 `NOASSERTION` | 已用于 V4 中文检索开发验证，只可作为回归对象，不计 M4 新盲测数量 |
| `hello-agents-1.0.3` | 不可用：所选目录无 `.git`，不能解析 HEAD | 未核验 Git snapshot | 本地 `LICENSE.txt` 为 CC BY-NC-SA 4.0；未绑定 Git SHA | 源码目录，尚不能作为固定 commit 的 M4 目标；README 指向 `datawhalechina/hello-agents`，获取上游 Git 副本仍需用户授权 |

三个具备 Git 历史的路径只读核验了本地 Git root、HEAD、tree inventory、至多 100 条历史和 tracked status；三者均为独立的所选 Git root，tracked status 前后保持一致。hello-agents 只检查目录顶层、Git 可用性、README 上游链接和许可证。没有读取源码正文、建索引或运行检索。测试数量按路径 `test/tests`、文件名前缀 `test_` 或后缀 `_test.py` 初筛，不能替代人工确认测试内容；许可证文件缺失也不等于已确认无其他许可声明。

两个新候选均涉及高光谱分类，规模和目录结构的差异仍须审阅。至少还需一个不同领域、同时有文档和测试的本地 Python Git 仓库。上表 Flask 已用于开发/验证，TypeScript 尚无 parser，均不能用来凑 M4 新仓库数量。不得自行下载；输入预检和冻结前的检查见 [M4 评测协议](evaluation-m4.md)。

### 既有固定 snapshot

首张表中 Flask 与 TypeScript 目标的 SHA 是 2026 年 10 月 17 日从对应仓库 `main` 观察到的 immutable snapshot。实际索引时仍必须重新解析并记录本地使用的完整 SHA；不能静默对移动的 `main` 做 benchmark。

Flask clone 位于被忽略的 `data/repositories/flask`，采用 no-checkout。它的空工作树可能让 Git status 报告 tracked paths 为 deleted，这是预期状态。V1.1 直接从 Git objects 读取，不检出文件。当前索引统计和 Flask 评测结果记录在 `docs/progress.md` 与 `eval/flask-baseline.json`。

TypeScript 目标尚未加入 parser 或评测集；在完成 TypeScript adapter、语言级 fixture 和固定 commit 校验前，不声称 RepoLens 支持 TypeScript。

## 许可与再分发

使用评测仓库时保留上游许可和 notice，不将复制的上游源码作为 RepoLens 产物发布。任何再分发前重新核对仓库当时的许可和条款。此处的 SHA、路径和统计是评测记录，不替代上游许可文本。
