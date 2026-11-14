"""python -m onefeed（003 T31）。

一个进程、一条命令：起 HTTP 服务 → 800ms 后开浏览器。
端口被占用时明确报出占用进程，不静默换端口。
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser

DEFAULT_PORT = 8787
DEFAULT_HOST = "127.0.0.1"


def _port_owner(port: int) -> str | None:
    """Windows: 从 netstat 里找监听该端口的 PID；其它系统返回 None。"""
    if os.name != "nt":
        return None
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=5, encoding="utf-8", errors="replace").stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 5 or not parts[0].upper().startswith("TCP"):
            continue
        if not parts[1].endswith(f":{port}") or parts[3].upper() != "LISTENING":
            continue
        return parts[4]
    return None


def _already_running(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.6)
        return sock.connect_ex((host, port)) == 0


def _fail_port_in_use(host: str, port: int) -> int:
    pid = _port_owner(port)
    if pid:
        print(f"端口 {port} 已被占用（PID {pid}）。", file=sys.stderr)
        print(f"  · 如果那就是 OneFeed，直接打开 http://{host}:{port}", file=sys.stderr)
        print(f"  · 想换端口：python -m onefeed --port {port + 1}", file=sys.stderr)
        print(f"  · 想结束它：taskkill /PID {pid} /F", file=sys.stderr)
    else:
        print(f"端口 {port} 已被占用，但没查出是哪个进程。", file=sys.stderr)
        print(f"  · 换一个：python -m onefeed --port {port + 1}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onefeed", description="OneFeed：把几个平台的信息流合成一屏")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ONEFEED_PORT", DEFAULT_PORT)))
    parser.add_argument("--host", default=os.environ.get("ONEFEED_HOST", DEFAULT_HOST))
    parser.add_argument("--demo", action="store_true", help="零网络演示模式（读本地样例）")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    if args.demo:
        os.environ["ONEFEED_DEMO"] = "1"

    if _already_running(args.host, args.port):
        return _fail_port_in_use(args.host, args.port)

    import uvicorn

    from . import __version__
    from .app import create_app

    app = create_app()
    url = f"http://{args.host}:{args.port}"
    print(f"OneFeed {__version__}  →  {url}", flush=True)
    print(f"  条目 {app.state.store.count()} 条 · 插件 {len(app.state.store.list_plugins())} 个"
          f"{' · DEMO 模式' if args.demo else ''}", flush=True)
    print("  Ctrl+C 退出", flush=True)

    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning",
                            access_log=False)
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    finally:
        app.state.store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
