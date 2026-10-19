"""Workbench operations over immutable Git snapshots, never working-tree source."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

from repolens.config import validate_data_directory
from repolens.domain import RepoLensError, stable_id
from repolens.git import GitRepository, _run_bounded, safe_repository_path
from repolens.index import DATABASE_NAME, IndexStore
from repolens.ingestion import ingest_or_reuse
from repolens.webapp import WebOperations


FIXTURES = Path(__file__).with_name("fixtures")


class WorkbenchService(WebOperations):
    def __init__(self, directory: Path):
        self.server = self
        self.default_data_dir = directory.resolve()
        self.runtime_api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip() or None
        self.on_event = None
        self.demo_lock = threading.Lock()

    def workspaces(self):
        if not (self.default_data_dir / DATABASE_NAME).is_file():
            return []
        grouped = {}
        with IndexStore(self.default_data_dir) as store:
            for snapshot in store.snapshots():
                if not self.path_authorized(snapshot["root"]):
                    continue
                identity = snapshot["repository_id"]
                entry = grouped.setdefault(identity, {
                    "workspace_id": identity, "name": Path(snapshot["root"]).name,
                    "repository": snapshot["root"], "snapshots": [],
                })
                entry["snapshots"].append(snapshot)
        return list(grouped.values())

    def workspace(self, identity):
        result = next((item for item in self.workspaces() if item["workspace_id"] == identity), None)
        if result is None:
            raise RepoLensError("仓库尚未导入，或工作区已不可用。")
        return result

    def path_authorized(self, repository):
        # Container operators explicitly authorize mount roots. Desktop users
        # authorize their chosen path through the local UI.
        roots = [Path(item).resolve() for item in os.environ.get("REPOLENS_REPOSITORY_ROOTS", "").split(os.pathsep) if item]
        if roots:
            roots.append((self.default_data_dir / "demo-repositories").resolve())
            requested = Path(repository).expanduser().resolve()
            return any(requested.is_relative_to(root) for root in roots)
        return True

    def validate_repository(self, repository):
        if not self.path_authorized(repository):
            raise RepoLensError("仓库路径不在已授权的目录内。")
        git = GitRepository(repository)
        if not all(self.path_authorized(path) for path in (git.root, git.git_directory)):
            raise RepoLensError("仓库或 Git 对象目录不在已授权的目录内。")
        validate_data_directory(self.default_data_dir, git.root)
        validate_data_directory(self.default_data_dir, git.git_directory)
        return git

    def import_repository(self, repository, ref):
        git = self.validate_repository(repository)
        snapshot = ingest_or_reuse(git.root, self.default_data_dir, ref)
        return {"workspace": self.workspace(snapshot["repository_id"]), "snapshot": snapshot}

    def execute(self, payload, emit):
        action = payload["action"]
        if action == "import":
            emit({"state": "index", "status": "started"})
            return self.import_repository(payload["repository"], payload["ref"])
        workspace = self.workspace(payload["workspace_id"])
        git = self.validate_repository(workspace["repository"])
        # Resolve mutable refs before any analysis or optional diff validation.
        sha = git.commit(payload["ref"]).sha
        common = {"repository": str(git.root), "ref": sha, "provider": payload.get("provider", "mock")}
        emit({"state": "version", "status": "ok", "commit_sha": sha})
        if action == "search":
            return self._version_search(common | {key: payload[key] for key in
                                        ("query", "retrieval", "limit", "path_prefix") if payload[key]})
        if action == "ask":
            return self._answer(common | {key: payload[key] for key in
                                ("question", "retrieval", "max_follow_ups")})
        if action == "impact":
            base_sha = git.commit(payload["base"]).sha
            if payload["diff"]:
                actual = _run_bounded(git.root, 1024 * 1024, "diff", "--no-ext-diff", "--no-textconv",
                                      "--no-color", "--no-renames", "--unified=3", base_sha, sha, "--")

                def normalized(text):
                    return [line for line in text.replace("\r\n", "\n").splitlines()
                            if not line.startswith("index ")]

                if normalized(payload["diff"]) != normalized(actual.decode("utf-8", errors="replace")):
                    raise RepoLensError("PR diff 与本地 base/head 不匹配；请提供对应提交的 unified=3 diff（不检测重命名）。")
                emit({"state": "diff_validation", "status": "ok"})
            report = self._impact(common | {"base": base_sha, "head": sha, "with_graph": payload["with_graph"]})
            return report
        if action == "graph":
            kind = payload["seed_kind"]
            selection = {"commit": True} if kind == "commit" else {kind: payload["seed"].strip()}
            if kind != "commit" and not payload["seed"].strip():
                raise RepoLensError("请输入函数名或文件路径。")
            return self._graph(common | selection | {"hops": payload["hops"], "max_nodes": 70, "max_edges": 140})
        if action == "agent":
            self.on_event = emit
            try:
                return self._agent(common | {"question": payload["question"], "base": payload["base"] or None,
                                            "budget": {"max_steps": payload["max_steps"],
                                                       "timeout_seconds": payload["timeout_seconds"]}})
            finally:
                self.on_event = None
        raise RepoLensError("不支持的任务类型。")

    def checked_snapshot(self, store, workspace_id, snapshot_id):
        self.workspace(workspace_id)
        snapshot = store.snapshot(snapshot_id)
        if snapshot["repository_id"] != workspace_id:
            raise RepoLensError("证据版本不属于所选仓库。")
        if not self.path_authorized(snapshot["root"]):
            raise RepoLensError("证据仓库不在已授权的目录内，请检查目录限制。")
        return snapshot

    def source(self, payload):
        if not safe_repository_path(payload.path):
            raise RepoLensError("请输入仓库内的相对文件路径。")
        with IndexStore(self.default_data_dir) as store:
            snapshot = self.checked_snapshot(store, payload.workspace_id, payload.snapshot_id)
            text = store.file_text(payload.snapshot_id, payload.path)
            if text is None:
                raise RepoLensError("该版本没有可显示的文本；文件可能已删除、为二进制或超出索引限制。")
            evidence = None
            if payload.evidence_id:
                evidence = store.evidence(payload.evidence_id, payload.snapshot_id)
                if evidence["path"] != payload.path:
                    raise RepoLensError("证据与所选文件不匹配。")
            return {"path": payload.path, "snapshot_id": payload.snapshot_id, "commit_sha": snapshot["commit_sha"],
                    "text": text, "evidence": evidence}

    def diff(self, payload):
        if not safe_repository_path(payload.path):
            raise RepoLensError("请输入仓库内的相对文件路径。")
        with IndexStore(self.default_data_dir) as store:
            base = self.checked_snapshot(store, payload.workspace_id, payload.base_snapshot_id)
            head = self.checked_snapshot(store, payload.workspace_id, payload.head_snapshot_id)
            if not store.files(base["snapshot_id"], path=payload.path) and not store.files(head["snapshot_id"], path=payload.path):
                raise RepoLensError("文件不属于所选版本。")
            before = store.file_text(base["snapshot_id"], payload.path)
            after = store.file_text(head["snapshot_id"], payload.path)
            # Missing files are empty sides; unsupported indexed files are explicit errors.
            for snapshot, text in ((base, before), (head, after)):
                if text is None and store.files(snapshot["snapshot_id"], path=payload.path):
                    raise RepoLensError("该文件未保存为可显示文本，无法显示 diff。")
            return {"path": payload.path, "base": {"commit_sha": base["commit_sha"], "text": before or ""},
                    "head": {"commit_sha": head["commit_sha"], "text": after or ""}}

    def details(self, identity):
        workspace = self.workspace(identity)
        git = self.validate_repository(workspace["repository"])
        latest = workspace["snapshots"][0]
        with IndexStore(self.default_data_dir) as store:
            history = store.history(latest["snapshot_id"], limit=100)
            files = store.files(latest["snapshot_id"])
        return workspace | {"branches": git.local_branches(latest["commit_sha"]),
                            "history": history, "files": files}

    def demo(self):
        with self.demo_lock:
            marker = self.default_data_dir / "workbench-demo.json"
            if marker.is_file():
                metadata = json.loads(marker.read_text(encoding="utf-8"))
                GitRepository(metadata["repository"]).commit(metadata["head"])
                return metadata
            demo_root = self.default_data_dir / "demo-repositories"
            demo_root.mkdir(parents=True, exist_ok=True)
            repository = Path(tempfile.mkdtemp(prefix="taskboard-", dir=demo_root))
            for source in (FIXTURES / "taskboard").rglob("*"):
                if source.is_file() and source.suffix in (".py", ".md"):
                    target = repository / source.relative_to(FIXTURES / "taskboard")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
            env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
            env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_AUTHOR_DATE="2026-01-01T00:00:00Z", GIT_COMMITTER_DATE="2026-01-01T00:00:00Z")

            def git(*args):
                return subprocess.run(["git", "-c", "init.templateDir=", "-c", "core.hooksPath=" + os.devnull,
                                       "-c", "core.autocrlf=false", "-c", "user.name=RepoLens Demo",
                                       "-c", "user.email=demo@example.invalid", "-C", str(repository), *args],
                                      env=env, capture_output=True, check=True, timeout=30).stdout.decode().strip()

            git("init", "--quiet")
            git("add", "--all")
            git("commit", "--quiet", "--no-gpg-sign", "-m", "Synthetic Taskboard baseline")
            base = git("rev-parse", "HEAD")
            service = repository / "service.py"
            service.write_text(service.read_text(encoding="utf-8").replace("return title", "return title.strip()"),
                               encoding="utf-8", newline="")
            git("add", "--all")
            git("commit", "--quiet", "--no-gpg-sign", "-m", "Normalize task titles")
            head = git("rev-parse", "HEAD")
            metadata = {"repository": str(repository), "base": base, "head": head,
                        "workspace_id": stable_id("repo", os.path.normcase(str(repository.resolve()))),
                        "question": "TaskService.create_task 如何处理任务标题？", "symbol": "TaskService.create_task"}
            marker.write_text(json.dumps(metadata, ensure_ascii=True), encoding="utf-8")
            return metadata
