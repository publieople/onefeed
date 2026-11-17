"""现场自检（preflight）的验收：检查项要能自己说清楚，不能一项失败整体崩。

跑法：
    uv run python tests/test_preflight.py
不联网、不开浏览器：只测纯逻辑与本机可控事实（python / 依赖 / 前端产物 / 端口）。

为什么要测它：preflight 是现场唯一的安全网，它自己抛异常就等于没有安全网。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onefeed import preflight  # noqa: E402

VERBOSE = "--verbose" in sys.argv
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


def write_plugin(root: Path, pid: str, *, bad: bool = False) -> None:
    target = root / pid
    target.mkdir(parents=True)
    data = {
        "schemaVersion": 1,
        "id": pid,
        "name": "演示",
        "version": "1.0.0",
        "capabilities": ["http"],
        "kinds": ["article"],
        "feeds": [{"id": "main", "name": "主"}],
        "entry": "index.js",
    }
    if bad:
        data["version"] = "不是版本号"
    (target / "plugin.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    (target / "index.js").write_text("module.exports = {};\n", encoding="utf-8")


def test_basic() -> None:
    for fn in (preflight.check_python, preflight.check_deps, preflight.check_web,
               preflight.check_state_dir):
        result = fn()
        check(isinstance(result, preflight.Check), f"{fn.__name__} 返回 Check")
        check(result.status in ("ok", "warn", "fail"), f"{fn.__name__} 状态合法")
    # 当前环境跑测试的 python 一定 >= 3.12，依赖与前端产物也应该齐
    check(preflight.check_python().status == "ok", "python 版本达标")
    check(preflight.check_deps().status == "ok", "依赖齐全")
    check(preflight.check_web().status == "ok", "前端产物存在")


def test_plugins() -> None:
    root = Path(tempfile.mkdtemp(prefix="onefeed-preflight-"))
    try:
        os.environ["ONEFEED_PLUGINS_DIR"] = str(root)
        empty = preflight.check_plugins()
        check(len(empty) == 1 and empty[0].status == "fail", "空插件目录判 fail")
        check("没有能加载的插件" in empty[0].detail, "空目录说清楚原因")

        write_plugin(root, "demo")
        good = preflight.check_plugins()
        check(good[0].status == "ok", "好插件判 ok")
        check("demo 1.0.0" in good[0].detail, "详情里有插件 id 与版本")

        write_plugin(root, "broken", bad=True)
        mixed = preflight.check_plugins()
        check(mixed[0].status == "warn", "混进坏插件降级为 warn")
        check("broken" in mixed[0].detail, "坏插件被点名")
    finally:
        os.environ.pop("ONEFEED_PLUGINS_DIR", None)
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def test_render() -> None:
    ok = [preflight.Check("A", "ok", "fine"), preflight.Check("B", "warn", "meh", "hint")]
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        code = preflight.render(ok)
    check(code == 0, "只有 warn 时退出码 0")
    check("降级" in buf.getvalue(), "结论里写明降级")

    bad = [preflight.Check("A", "fail", "boom", "fix it")]
    with contextlib.redirect_stdout(io.StringIO()) as buf:
        code = preflight.render(bad)
    check(code == 1, "有 fail 时退出码 1")
    check("fix it" in buf.getvalue(), "fail 的修法会打出来")


def test_port() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        result = preflight.check_port(port)
    check(result.status == "warn", "被非 OneFeed 程序占用时判 warn")
    check(str(port) in result.name, "名称里带端口号")


def test_login() -> None:
    import shutil

    import plugin_runtime.paths as paths

    from onefeed.auth import SPECS

    tmp = Path(tempfile.mkdtemp(prefix="onefeed-preflight-home-"))
    old_home, old_cache = os.environ.get("ONEFEED_HOME"), paths._cache
    try:
        os.environ["ONEFEED_HOME"] = str(tmp)
        paths._cache = None
        results = preflight.check_login()
        for spec in SPECS.values():
            hit = [r for r in results if r.name == f"{spec['label']}登录态"]
            check(len(hit) == 1, f"{spec['label']} 有一条登录检查")
            check(hit[0].status == "warn", f"{spec['label']} 没 cookie 时判 warn")
        # 造一个判据 cookie 在的文件，应该翻成 ok
        first_id, first_spec = next(iter(SPECS.items()))
        cookies = tmp / "cookies"
        cookies.mkdir(parents=True, exist_ok=True)
        (cookies / f"{first_id}.json").write_text(
            json.dumps({"cookies": [{"name": first_spec["cookies"][0], "value": "x"}]},
                       ensure_ascii=False), encoding="utf-8")
        again = preflight.check_login()
        hit = [r for r in again if r.name == f"{first_spec['label']}登录态"][0]
        check(hit.status == "ok", "判据 cookie 在就判 ok")
    finally:
        if old_home is None:
            os.environ.pop("ONEFEED_HOME", None)
        else:
            os.environ["ONEFEED_HOME"] = old_home
        paths._cache = old_cache
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    tests = [test_basic, test_plugins, test_render, test_port, test_login]
    for fn in tests:
        fn()
        print(f"  {fn.__name__} ok")
    print(f"✅ preflight {CHECKS} 项全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
