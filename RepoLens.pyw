"""Double-clickable Windows launcher for the local RepoLens browser UI."""

from pathlib import Path
import importlib.util
import os
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

def launch():
    """Reuse the prepared workbench environment, with no terminal window."""
    prepared = ROOT / "data" / "v5-web-venv" / "Scripts" / "pythonw.exe"
    if prepared.is_file() and Path(sys.executable).resolve() != prepared.resolve():
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        subprocess.Popen([str(prepared), "-m", "repolens.workbench.launcher"], cwd=ROOT,
                         env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return
    if importlib.util.find_spec("fastapi") and importlib.util.find_spec("uvicorn"):
        from repolens.workbench.launcher import main
        main()
    else:
        from tkinter import messagebox
        messagebox.showerror("RepoLens", "工作台依赖尚未安装。请按 docs/deployment.md 完成首次准备。")


launch()
