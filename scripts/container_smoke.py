"""Check a running loopback-published container using only the standard library."""

import argparse
import json
import time
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8770")
    parser.add_argument("--repository", help="Optional authorized container mount path to import")
    args = parser.parse_args()

    def call(path, data=None):
        body = json.dumps(data).encode() if data is not None else None
        request = Request(args.url + path, data=body,
                          headers={"Content-Type": "application/json"} if body else {})
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            if path == "/":
                assert b"/assets/" in raw
                return {}
            assert response.headers.get("X-Request-ID")
            return json.loads(raw)

    call("/")
    assert call("/api/health")["stage"] == "V6"
    demo = call("/api/demo", {})
    task = demo["task"]
    deadline = time.monotonic() + 90
    while task["status"] in ("queued", "running") and time.monotonic() < deadline:
        time.sleep(.2)
        task = call("/api/tasks/" + task["id"])
    assert task["status"] == "completed", task.get("error")
    if args.repository:
        task = call("/api/tasks", {"action": "import", "repository": args.repository})
        deadline = time.monotonic() + 90
        while task["status"] in ("queued", "running") and time.monotonic() < deadline:
            time.sleep(.2)
            task = call("/api/tasks/" + task["id"])
        assert task["status"] == "completed", task.get("error")
    assert call("/api/metrics")["schema_version"] == "repolens.metrics.v1"
    print(json.dumps({"ok": True, "stage": "V6", "demo_import": "completed", "metrics": True,
                      "mounted_repository_import": bool(args.repository)}))


if __name__ == "__main__":
    main()
