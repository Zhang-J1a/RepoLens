"""Generate or check the current OpenAPI contract without starting a server."""

import argparse
import json
from pathlib import Path

from repolens.workbench.api import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    target = root / "docs/openapi-v6.json"
    app = create_app(root / "data/openapi-check")
    try:
        schema = app.openapi()
        if args.check:
            if json.loads(target.read_text(encoding="utf-8")) != schema:
                raise SystemExit("OpenAPI changed; regenerate the contract and TypeScript types.")
        else:
            target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finally:
        app.state.jobs.close()


if __name__ == "__main__":
    main()
