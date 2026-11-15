"""python -m onefeed（003 T31）。

一个进程、一条命令：起 HTTP 服务 → 800ms 后开浏览器。
默认端口被占用时：如果占用者是 OneFeed，直接把浏览器指过去；否则自动往后找一个空端口。
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
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


def _is_onefeed(host: str, port: int) -> bool:
    """占用者是不是已经跑着的 OneFeed（看 /api/health 的指纹，不去猜进程名）。"""
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=1.2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return bool(data.get("ok")) and "version" in data and "platforms" in data
    except Exception:
        return False


def _free_port(host: str, start: int, tries: int = 10) -> int | None:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.4)
            if sock.connect_ex((host, port)) != 0:
                return port
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="onefeed", description="OneFeed：把几个平台的信息流合成一屏")
    parser.add_argument("--port", type=int, default=int(os.environ.get("ONEFEED_PORT", DEFAULT_PORT)))
    parser.add_argument("--host", default=os.environ.get("ONEFEED_HOST", DEFAULT_HOST))
    parser.add_argument("--demo", action="store_true", help="零网络演示模式（读本地样例）")
    parser.add_argument("--warmup", action="store_true", help="采集一轮并写入 fixtures/，供 --demo 使用")
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
        if _is_onefeed(args.host, args.port):
            url = f"http://{args.host}:{args.port}"
            print(f"OneFeed 已经在 {url} 跑着，直接把浏览器指过去。", flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        pid = _port_owner(args.port)
        new_port = _free_port(args.host, args.port + 1)
        if new_port is None:
            print(f"端口 {args.port} 被占用（{'PID ' + pid if pid else '进程未知'}），"
                  f"后面 10 个端口也都被占了；用 --port 指定一个空闲端口。", file=sys.stderr)
            return 1
        print(f"端口 {args.port} 被占用（{'PID ' + pid if pid else '进程未知'}），"
              f"自动改用 {new_port}。", flush=True)
        if pid:
            kill = (f"taskkill /PID {pid} /T /F" if os.name == "nt" else f"kill -9 {pid}")
            print(f"  如果那是上次没关掉的 OneFeed：{kill}", flush=True)
        print(f"  想固定端口就加 --port {new_port}", flush=True)
        args.port = new_port

    import uvicorn

    from . import __version__
    from .app import create_app

    app = create_app()
    store = app.state.store
    refresher = app.state.refresher
    if args.warmup:
        ok, _state = refresher.trigger(warmup=True)
        print(f"  预热采集{'已启动' if ok else '没启动（可能正在跑）'}：结果写进 fixtures/", flush=True)
    elif store.count() == 0 or args.demo:
        refresher.trigger()
        print("  库里还没有内容，已在后台拉一轮（进度看页面上的刷新条）", flush=True)
    url = f"http://{args.host}:{args.port}"
    print(f"OneFeed {__version__}  →  {url}", flush=True)
    print(f"  条目 {store.count()} 条 · 插件 {len(store.list_plugins())} 个"
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