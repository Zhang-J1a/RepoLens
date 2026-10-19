"""Read-only prerequisite checks without repository or index access."""

import platform
import shutil
import sqlite3
import subprocess
import sys

from repolens import __version__
from repolens.git import _environment


def doctor() -> dict:
    checks = {"python": {"ok": sys.version_info >= (3, 12), "version": platform.python_version()}}
    git = shutil.which("git")
    checks["git"] = {"ok": False, "hint": "Install Git and add it to PATH."}
    if git:
        try:
            result = subprocess.run([git, "--version"], env=_environment(), capture_output=True,
                                    timeout=5, check=False, text=True)
            if result.returncode == 0:
                checks["git"] = {"ok": True, "version": result.stdout.strip()}
        except (OSError, subprocess.TimeoutExpired):
            pass
    connection = None
    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE probe USING fts5(content)")
        checks["sqlite_fts5"] = {"ok": True, "version": sqlite3.sqlite_version}
    except sqlite3.Error:
        checks["sqlite_fts5"] = {"ok": False, "hint": "Use a Python build with SQLite FTS5 support."}
    finally:
        if connection is not None:
            connection.close()
    return {"ok": all(check["ok"] for check in checks.values()), "version": __version__, "checks": checks}
