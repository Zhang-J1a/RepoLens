import os
from pathlib import Path

from repolens.domain import RepoLensError


def data_directory(explicit: str | Path | None = None) -> Path:
    chosen = explicit or os.environ.get("REPOLENS_DATA_DIR")
    if chosen:
        return Path(chosen).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return (base / "RepoLens").resolve()
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return (base / "repolens").resolve()


def validate_data_directory(directory: Path, repository: Path) -> None:
    if directory.is_relative_to(repository):
        raise RepoLensError("Index data must be outside the target repository; choose another --data-dir.")
