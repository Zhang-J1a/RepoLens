"""Loopback launcher; a reserved socket chooses an actually free port."""

import argparse
import os
import socket
import sys
import threading
import webbrowser

from repolens.config import data_directory
from repolens.observability import configure_logging


def main():
    import uvicorn
    from repolens.workbench.api import create_app

    parser = argparse.ArgumentParser(description="RepoLens V6 本地分析工作台")
    parser.add_argument("--host", choices=("127.0.0.1", "0.0.0.0"), default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--data-dir")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be 0..65535")
    if args.host == "0.0.0.0" and os.environ.get("REPOLENS_CONTAINER") != "1":
        parser.error("0.0.0.0 is reserved for the loopback-published container deployment")
    configure_logging(os.environ.get("REPOLENS_LOG_LEVEL", "INFO"))
    sock = socket.socket()
    sock.bind((args.host, args.port))
    display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    url = f"http://{display_host}:{sock.getsockname()[1]}/"
    if sys.stdout is not None:
        print(url, flush=True)
    app = create_app(data_directory(args.data_dir))
    log_options = {"log_config": None} if sys.stdout is None or sys.stderr is None else {}
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False,
                                          use_colors=False, **log_options))
    if not args.no_browser:
        def open_when_ready():
            if server.started:
                webbrowser.open(url)
            elif not server.should_exit:
                threading.Timer(0.1, open_when_ready).start()
        threading.Timer(0.1, open_when_ready).start()
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
