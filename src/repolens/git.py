"""Read committed Git objects only; no checkout, filters, hooks, or network."""

from contextlib import AbstractContextManager
from datetime import datetime, timezone
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

from repolens.domain import (
    Commit,
    MAX_HISTORY_COMMITS,
    MAX_HISTORY_MESSAGE_BYTES,
    MAX_TREE_ENTRIES,
    RepoLensError,
    TreeEntry,
)


def _environment() -> dict[str, str]:
    # Inherited Git overrides must not redirect reads to another repository.
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update(
        GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0",
        GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1",
    )
    return env


def _command(root: Path, *args: str) -> list[str]:
    return [
        "git", "--no-pager", "-c", f"safe.directory={root}",
        "-c", "core.fsmonitor=false", "-c", "gc.auto=0",
        "-c", "maintenance.auto=false", "-C", str(root), *args,
    ]


def _run(root: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            _command(root, *args), env=_environment(), capture_output=True,
            timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RepoLensError("Git read failed; check the Git installation and local repository.") from exc
    if result.returncode:
        raise RepoLensError("Git read failed; verify the repository and that the requested commit is available locally.")
    return result.stdout


def _run_bounded(root: Path, max_output_bytes: int, *args: str) -> bytes:
    """Run a read-only Git command with an explicit stdout bound."""

    try:
        result = subprocess.run(
            _command(root, *args), env=_environment(), capture_output=True,
            timeout=30, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RepoLensError("Git read failed; check the Git installation and local repository.") from exc
    if result.returncode:
        raise RepoLensError("Git read failed; verify the repository and that the requested commit is available locally.")
    if len(result.stdout) > max_output_bytes:
        raise RepoLensError("Git output exceeds the current bounded analysis limit; narrow the requested range or file set.")
    return result.stdout


def safe_repository_path(path: str) -> bool:
    pure = PurePosixPath(path)
    return bool(path) and not pure.is_absolute() and not any(
        part in (".", "..") or "\\" in part or ":" in part or "\x00" in part
        for part in path.split("/")
    ) and all(path.split("/"))


class GitRepository:
    def __init__(self, path: str | Path):
        try:
            requested = Path(path).expanduser().resolve(strict=True)
        except OSError as exc:
            raise RepoLensError("Repository path does not exist; choose a local Git repository.") from exc
        if not requested.is_dir():
            raise RepoLensError("Repository path must be a directory.")
        bare = _run(requested, "rev-parse", "--is-bare-repository").strip() == b"true"
        option = "--absolute-git-dir" if bare else "--show-toplevel"
        self.root = Path(_run(requested, "rev-parse", option).decode("utf-8").strip()).resolve()
        self.git_directory = Path(
            _run(requested, "rev-parse", "--absolute-git-dir").decode("utf-8").strip()
        ).resolve()

    def commit(self, ref: str) -> Commit:
        raw = _run(self.root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        sha = raw.decode("ascii").strip()
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha):
            raise RepoLensError("Git returned an invalid commit identity.")
        metadata = _run(self.root, "show", "-s", "--format=%P%x00%an%x00%aI%x00%B", sha)
        try:
            parents, author, timestamp, message = metadata.decode("utf-8", errors="replace").split("\x00", 3)
            authored_at = datetime.fromisoformat(timestamp).astimezone(timezone.utc).isoformat()
        except ValueError as exc:
            raise RepoLensError("Git returned invalid commit metadata; choose another locally available commit.") from exc
        return Commit(sha, tuple(parents.split()), author, authored_at, message.rstrip("\n"))

    def inventory(self, sha: str) -> list[TreeEntry]:
        raw = _run(self.root, "ls-tree", "-r", "-z", "-l", "--full-tree", sha)
        records = raw.rstrip(b"\x00").split(b"\x00") if raw else []
        if len(records) > MAX_TREE_ENTRIES:
            raise RepoLensError(f"Repository exceeds the current {MAX_TREE_ENTRIES}-entry inventory limit.")
        entries = []
        for record in records:
            header, raw_path = record.split(b"\t", 1)
            mode, _, object_id, size = header.split()
            try:
                path = raw_path.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise RepoLensError("Repository contains a non-UTF-8 path; this snapshot is not supported yet.") from exc
            if not safe_repository_path(path):
                raise RepoLensError("Repository contains a non-portable or unsafe path; indexing was stopped.")
            entries.append(TreeEntry(
                path, object_id.decode("ascii"), mode.decode("ascii"),
                0 if size == b"-" else int(size),
            ))
        return entries

    def history(self, sha: str, *, max_count: int = MAX_HISTORY_COMMITS) -> list[Commit]:
        """Read bounded commit history reachable from a selected snapshot."""

        if not 1 <= max_count <= MAX_HISTORY_COMMITS:
            raise RepoLensError(f"History commit limit must be between 1 and {MAX_HISTORY_COMMITS}.")
        raw = _run_bounded(
            self.root,
            max_count * MAX_HISTORY_MESSAGE_BYTES,
            "log", f"--max-count={max_count}",
            "--format=%H%x00%P%x00%an%x00%aI%x00%B%x00", sha, "--",
        )
        fields = raw.decode("utf-8", errors="replace").split("\x00")
        commits = []
        for offset in range(0, len(fields) - 1, 5):
            commit_sha, parents, author, timestamp, message = fields[offset:offset + 5]
            commit_sha = commit_sha.strip()
            parents = parents.strip()
            author = author.strip()
            timestamp = timestamp.strip()
            message = message.lstrip("\n")
            if not commit_sha.strip():
                continue
            if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit_sha):
                raise RepoLensError("Git returned an invalid history commit identity.")
            if len(message.encode("utf-8")) > MAX_HISTORY_MESSAGE_BYTES:
                raise RepoLensError("A Git commit message exceeds the current history size limit.")
            try:
                authored_at = datetime.fromisoformat(timestamp).astimezone(timezone.utc).isoformat()
            except ValueError as exc:
                raise RepoLensError("Git returned invalid history metadata.") from exc
            commits.append(Commit(
                commit_sha,
                tuple(parents.split()),
                author,
                authored_at,
                message.rstrip("\n"),
            ))
        if len(commits) > max_count:
            raise RepoLensError("Git returned more history commits than requested.")
        return commits

    def local_branches(self, sha: str) -> list[str]:
        """Return local branches that contain the selected commit."""

        raw = _run_bounded(
            self.root,
            1024 * 1024,
            "for-each-ref", "--format=%(refname:short)%00", "--contains", sha, "refs/heads",
        )
        branches = []
        for value in raw.decode("utf-8", errors="strict").split("\x00"):
            branch = value.strip()
            if branch:
                branches.append(branch)
        return sorted(dict.fromkeys(branches))

    def changed_files(self, base_sha: str, head_sha: str) -> list[dict[str, str | None]]:
        """Return changed paths without following renames or reading the worktree."""

        raw = _run_bounded(
            self.root,
            2 * 1024 * 1024,
            "diff", "--no-ext-diff", "--no-textconv", "--no-renames",
            "--name-status", "-z", "--diff-filter=ACDMRTUXB", base_sha, head_sha, "--",
        )
        fields = raw.rstrip(b"\x00").split(b"\x00") if raw else []
        changes = []
        index = 0
        while index < len(fields):
            try:
                status = fields[index].decode("ascii")
                path = fields[index + 1].decode("utf-8")
            except (UnicodeDecodeError, IndexError, ValueError) as exc:
                raise RepoLensError("Git returned an invalid changed-file record.") from exc
            index += 2
            if len(status) != 1 or status not in "ACDMRTUXB" or not safe_repository_path(path):
                raise RepoLensError("Git returned an unsupported or unsafe changed-file path.")
            changes.append({"status": status, "path": path, "old_path": None})
        return changes

    def diff_hunks(self, base_sha: str, head_sha: str, path: str) -> list[dict[str, int]]:
        """Return old/new line ranges for a path from a zero-context local diff."""

        if not safe_repository_path(path):
            raise RepoLensError("Diff path must be a safe repository-relative POSIX path.")
        raw = _run_bounded(
            self.root,
            4 * 1024 * 1024,
            "diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--unified=0",
            base_sha, head_sha, "--", path,
        )
        hunks = []
        for raw_line in raw.decode("utf-8", errors="replace").splitlines():
            if not raw_line.startswith("@@ "):
                continue
            match = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", raw_line)
            if not match:
                raise RepoLensError("Git returned an invalid diff hunk header.")
            old_start, old_count, new_start, new_count = match.groups()
            hunks.append({
                "old_start": int(old_start),
                "old_count": int(old_count or 1),
                "new_start": int(new_start),
                "new_count": int(new_count or 1),
            })
        return hunks

    def blobs(self) -> "BlobReader":
        return BlobReader(self.root)


class BlobReader(AbstractContextManager):
    def __init__(self, root: Path):
        try:
            self.process = subprocess.Popen(
                _command(root, "cat-file", "--batch"), env=_environment(),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise RepoLensError("Could not start the local Git object reader.") from exc

    def read(self, entry: TreeEntry) -> bytes:
        try:
            self.process.stdin.write(entry.object_id.encode("ascii") + b"\n")
            self.process.stdin.flush()
            header = self.process.stdout.readline(256).split()
            if header != [entry.object_id.encode("ascii"), b"blob", str(entry.size).encode("ascii")]:
                raise RepoLensError("A required Git blob is missing or inconsistent; fetch it explicitly before indexing.")
            data = self.process.stdout.read(entry.size)
            if len(data) != entry.size or self.process.stdout.read(1) != b"\n":
                raise RepoLensError("Git object reader returned incomplete source content.")
            return data
        except (OSError, ValueError) as exc:
            raise RepoLensError("Git object reader failed while reading source content.") from exc

    def __exit__(self, *exc_info):
        self.process.stdin.close()
        self.process.stdout.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        return False
