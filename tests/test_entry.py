"""T31 验收：端口占用检测。

跑法：python tests/test_entry.py
不真的起服务，只验证「占用 → 报出 PID」这条路径，以及 --help 能跑。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onefeed.__main__ import _already_running, _port_owner  # noqa: E402

CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)


def main() -> int:
    # 占一个随机空闲端口
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]

        check(_already_running("127.0.0.1", port) is True, "监听中的端口判定为占用")
        pid = _port_owner(port)
        if os.name == "nt":
            check(pid == str(os.getpid()), f"占用进程 PID 认得对（{pid}）")
        else:
            check(pid is None, "非 Windows 不查 PID")

        # 未被占用的端口
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as free:
            free.bind(("127.0.0.1", 0))
            free_port = free.getsockname()[1]
        check(_already_running("127.0.0.1", free_port) is False, "空闲端口判定为可用")

    # 入口脚本能加载并给出帮助
    proc = subprocess.run([sys.executable, "-m", "onefeed", "--help"], cwd=str(ROOT),
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=60)
    check(proc.returncode == 0, "--help 正常退出")
    for flag in ("--port", "--demo", "--no-browser"):
        check(flag in proc.stdout, f"--help 列出 {flag}")

    print(f"T31 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
