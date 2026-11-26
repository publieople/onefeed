"""worker 超时不能把宿主一起杀掉。

跑法：
    python tests/test_host.py
只替换 Popen 与 _kill_tree，不真的起子进程。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin_runtime import host as host_mod  # noqa: E402

VERBOSE = "--verbose" in sys.argv
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


def test_timeout_isolates_worker_group() -> None:
    captured: dict = {}
    calls: list[str] = []

    class FakeProc:
        pid = 43210

        def communicate(self, timeout=None):
            calls.append("timeout" if timeout is not None else "finish")
            if timeout is not None:
                raise subprocess.TimeoutExpired(["worker"], timeout)
            return "", ""

    def fake_popen(_cmd, **kwargs):
        captured.update(kwargs)
        return FakeProc()

    killed: list[int] = []
    with tempfile.TemporaryDirectory() as tmp:
        plugin = Path(tmp)
        h = host_mod.PluginHost(plugins_dir=plugin)
        h._manifests = {"demo": SimpleNamespace(path=plugin, capabilities=[])}
        with patch.object(host_mod.subprocess, "Popen", fake_popen), \
                patch.object(host_mod, "_kill_tree", lambda pid: killed.append(pid)):
            out = h.run("demo", "pull")

    check(calls == ["timeout", "finish"], "超时后仍会收回子进程输出")
    check(killed == [FakeProc.pid], "超时会杀掉 worker 进程树")
    check(out["ok"] is False and "timeout" in out["error"], "超时返回可读错误")
    if os.name != "nt":
        check(captured.get("start_new_session") is True,
              "POSIX 下 worker 使用独立进程组（killpg 不会打到宿主）")


def main() -> int:
    try:
        test_timeout_isolates_worker_group()
    except AssertionError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"test_host: {CHECKS} 项检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
