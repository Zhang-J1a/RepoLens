# 首批评测仓库

以下仓库只作为真实评测输入，不是 RepoLens 的源码依赖或产品范围。用户使用 RepoLens 时，可以选择自己拥有或获授权读取的任意本地 Git 仓库。`all-in-rag` 和 `AgentGuide` 不是评测目标。

| 语言 | 仓库 | 许可证据 | 2026-10-17 观察到的 snapshot | 评测用途 |
|---|---|---|---|---|
| Python | `pallets/flask` | `pyproject.toml` 声明 BSD-3-Clause，存在 `LICENSE.txt` | `d086db856be187255b8ec61ef409357393020f32` | 主结构/检索 benchmark；有常规 package、测试、文档和历史 |
| TypeScript | `sindresorhus/is` | `package.json` 声明 MIT，存在 license 文件 | `e9c026c611c1160eaad50da00be4e676b626018f` | 后续用于验证第二语言 adapter |

## 使用规则

上表 SHA 是 2026 年 10 月 17 日从对应仓库 `main` 观察到的 immutable snapshot。实际索引时仍必须重新解析并记录本地使用的完整 SHA；不能静默对移动的 `main` 做 benchmark。

Flask clone 位于被忽略的 `data/repositories/flask`，采用 no-checkout。它的空工作树可能让 Git status 报告 tracked paths 为 deleted，这是预期状态。V1.1 直接从 Git objects 读取，不检出文件。当前索引统计和 Flask 评测结果记录在 `docs/progress.md` 与 `eval/flask-baseline.json`。

TypeScript 目标尚未加入 parser 或评测集；在完成 TypeScript adapter、语言级 fixture 和固定 commit 校验前，不声称 RepoLens 支持 TypeScript。

## 许可与再分发

使用评测仓库时保留上游许可和 notice，不将复制的上游源码作为 RepoLens 产物发布。任何再分发前重新核对仓库当时的许可和条款。此处的 SHA、路径和统计是评测记录，不替代上游许可文本。
