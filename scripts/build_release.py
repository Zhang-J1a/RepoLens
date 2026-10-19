"""Build from a fresh staging directory and reject stale frontend assets."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    static = root / "src/repolens/workbench/static"
    if not (static / "index.html").is_file():
        raise SystemExit("Build the frontend with npm run build --prefix apps/web first.")
    with tempfile.TemporaryDirectory(prefix="repolens-release-") as temporary:
        stage = Path(temporary)
        for name in ("pyproject.toml", "README.md"):
            shutil.copyfile(root / name, stage / name)
        shutil.copytree(root / "src/repolens", stage / "src/repolens",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        subprocess.run([sys.executable, "-m", "pip", "wheel", ".", "--no-cache-dir", "--no-deps", "--no-build-isolation",
                        "--no-index", "--disable-pip-version-check", "--wheel-dir", str(root / "dist")],
                       cwd=stage, check=True)
    from repolens import __version__
    wheel = root / "dist" / f"repolens-{__version__}-py3-none-any.whl"
    prefix = "repolens/workbench/static/"
    expected = {prefix + path.relative_to(static).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in static.rglob("*") if path.is_file()}
    with zipfile.ZipFile(wheel) as archive:
        actual = {name: hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()
                  if name.startswith(prefix) and not name.endswith("/")}
    if expected != actual:
        raise SystemExit("Wheel frontend files differ from the current build.")
    report = {"stage": "V6", "wheel": wheel.name, "version": __version__,
              "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
              "frontend_files": len(expected), "stale_assets": 0, "asset_hashes": expected}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "asset_hashes"}, indent=2))


if __name__ == "__main__":
    main()
