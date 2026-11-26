"""现场自检：python -m onefeed --preflight。

为什么单独做一个：比赛现场只有一次机会，出问题要在十秒内看出是哪一环，
而不是翻日志猜。这里把「能不能演」拆成互不相干的检查，每项只回答三件事：
现在能不能用、不能用时降级成什么、修它要敲哪条命令。

口径：
- 全部检查都短超时、不写库、不开浏览器窗口（只探测内核路径）；
- 输出前缀用 ASCII（OK / WARN / FAIL），因为现场可能拿到 cp936 的控制台；
- 有 FAIL 退出码 1，否则 0，方便脚本串起来。
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import sqlite3
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from plugin_runtime.paths import state_root

ROOT = Path(__file__).resolve().parent.parent
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

DEPS = {
    "fastapi": "FastAPI",
    "uvicorn": "uvicorn",
    "quickjs": "QuickJS（插件沙箱）",
    "playwright": "Playwright（浏览器类插件）",
    "pydantic_ai": "Pydantic AI（Agent）",
}


@dataclass
class Check:
    name: str
    status: str            # ok / warn / fail
    detail: str
    hint: str = ""


# ---------------------------------------------------------------- 单项检查

def check_python() -> Check:
    v = sys.version_info
    text = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 12):
        return Check("Python", "ok", f"{text} · {sys.executable}")
    return Check("Python", "fail", f"{text}（需要 3.12+）",
                 "用 uv run 启动会自动挑对版本；直接 python 的话先切环境")


def check_deps() -> Check:
    missing = [label for mod, label in DEPS.items() if importlib.util.find_spec(mod) is None]
    if not missing:
        return Check("依赖", "ok", " / ".join(DEPS) + " 都在")
    return Check("依赖", "fail", "缺：" + "、".join(missing),
                 "在仓库根执行 uv sync（或 uv run python -m onefeed，uv 会自动补齐）")


def check_browser() -> Check:
    from plugin_runtime.capabilities import _find_chrome

    path = _find_chrome()
    if path:
        name = Path(path).name
        return Check("浏览器内核", "ok", f"{name} · {path}")
    return Check("浏览器内核", "fail", "没找到 Chrome / Edge",
                 "抖音、小红书、知乎三个插件全靠它；装 Chrome 后重跑一次自检")


def check_state_dir() -> Check:
    root = state_root()
    probe = root / ".preflight-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check("状态目录", "fail", f"{root} 写不进去：{exc}",
                     "设 ONEFEED_HOME 指到可写目录，例如 ONEFEED_HOME=D:\\onefeed-home")
    return Check("状态目录", "ok", str(root))


def check_plugins() -> list[Check]:
    from onefeed import settings as settings_mod
    from plugin_runtime.manifest import ManifestError, load_manifest

    conf = settings_mod.load()
    raw = str(conf.get("plugins_dir") or "")
    try:
        root = settings_mod.resolve_plugins_dir(raw)
    except Exception as exc:                     # noqa: BLE001 - 配置错就是错
        return [Check("插件目录", "fail", f"解析失败：{exc}", "看设置页的「插件目录」")]
    if not root.is_dir():
        return [Check("插件目录", "fail", f"不存在：{root}",
                      "把插件仓库放好，或 --plugins-dir / ONEFEED_PLUGINS_DIR 指过去")]

    dirs = [p for p in sorted(root.iterdir())
            if p.is_dir() and not p.name.startswith((".", "__"))]
    good: list[str] = []
    bad: list[str] = []
    for item in dirs:
        try:
            man = load_manifest(item)
            good.append(f"{man.id} {man.version}")
        except (ManifestError, OSError) as exc:
            bad.append(f"{item.name}: {exc}")

    if not good:
        return [Check("插件目录", "fail", f"{root} 下没有能加载的插件",
                      "插件仓库是不是空的？git submodule / 手动 clone 一下")]
    detail = f"{len(good)} 个 · " + "、".join(good)
    if bad:
        return [Check("插件目录", "warn", detail + f"；坏掉 {len(bad)} 个：" + "；".join(bad),
                      "坏掉的插件会被跳过，不影响其它平台")]
    return [Check("插件目录", "ok", detail)]


def check_database() -> Check:
    db = state_root() / "onefeed.db"
    if not db.is_file():
        return Check("数据库", "warn", "还没有库（首次启动会自动采一轮）",
                     "想立刻有内容就启动后点页面右上角的刷新")
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            total = conn.execute("select count(*) from items").fetchone()[0]
            rows = conn.execute(
                "select platform, count(*) from items group by platform order by 2 desc"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return Check("数据库", "fail", f"打不开：{exc}", "删掉 .onefeed/onefeed.db 让宿主重建")
    if not total:
        return Check("数据库", "warn", "库是空的", "启动后点刷新采一轮")
    parts = "、".join(f"{name} {cnt}" for name, cnt in rows)
    size_mb = db.stat().st_size / 1024 / 1024
    return Check("数据库", "ok", f"{total} 条（{parts}）· {size_mb:.1f} MB")


def check_web() -> Check:
    dist = ROOT / "web" / "dist" / "index.html"
    if dist.is_file():
        assets = list((ROOT / "web" / "dist" / "assets").glob("*.js"))
        return Check("前端产物", "ok", f"{dist.relative_to(ROOT)} · {len(assets)} 个 js")
    return Check("前端产物", "fail", "没有 web/dist/index.html",
                 "cd web && npm install && npm run build")


def check_login() -> list[Check]:
    from onefeed.auth import CLI_SPECS, SPECS

    out: list[Check] = []
    cookies_dir = state_root() / "cookies"
    for plugin_id, spec in SPECS.items():
        label = spec.get("label", plugin_id)
        path = cookies_dir / f"{plugin_id}.json"
        if not path.is_file():
            out.append(Check(f"{label}登录态", "warn", "未登录 · " + str(spec.get("impact", "")),
                             f"设置页点「打开登录窗口」，或 POST /api/auth/{plugin_id}/login"))
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            names = {c.get("name") for c in data.get("cookies", []) if isinstance(c, dict)}
        except (OSError, json.JSONDecodeError) as exc:
            out.append(Check(f"{label}登录态", "warn", f"cookie 文件读不了：{exc}",
                             "重新登录一次"))
            continue
        want = tuple(spec.get("cookies") or ())
        hit = [n for n in want if n in names]
        if hit:
            out.append(Check(f"{label}登录态", "ok",
                             f"已登录 · {len(names)} 个 cookie（判据 {hit[0]} 在）"))
        else:
            out.append(Check(f"{label}登录态", "warn",
                             f"文件在但判据 {want} 缺失，会话大概率过期了",
                             "重新扫码登录一次"))
    for plugin_id, spec in CLI_SPECS.items():
        cmd = spec.get("command", "")
        exe = cmd.split()[0] if cmd else ""
        found = shutil.which(exe) if exe else None
        if found:
            out.append(Check(f"{spec.get('label', plugin_id)} CLI", "ok", f"{exe} · {found}"))
        else:
            out.append(Check(f"{spec.get('label', plugin_id)} CLI", "fail",
                             f"PATH 里没有 {exe}",
                             "B 站插件靠它取数；装好 bili CLI 或临时停用 B 站插件"))
    return out


def check_port(port: int) -> Check:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.6)
        busy = sock.connect_ex(("127.0.0.1", port)) == 0
    if not busy:
        return Check(f"端口 {port}", "ok", "空闲")
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if data.get("ok") and "version" in data:
            return Check(f"端口 {port}", "ok",
                         f"已经有一个 OneFeed 在跑（{data.get('items', '?')} 条 · "
                         f"插件 {data.get('plugins', '?')} 个）")
    except Exception:                            # noqa: BLE001 - 占用的可能是别的服务
        pass
    return Check(f"端口 {port}", "warn", "被别的程序占着",
                 f"换个端口：--port {port + 1}，或者先关掉占用的进程")


def check_network() -> Check:
    targets = [
        ("registry", "https://cdn.jsdelivr.net/gh/publieople/onefeed-plugins@main/registry.json"),
        ("B 站接口", "https://api.bilibili.com/x/web-interface/popular?ps=1&pn=1"),
    ]
    ok: list[str] = []
    bad: list[str] = []
    for name, url in targets:
        started = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    ok.append(f"{name} {(time.time() - started) * 1000:.0f}ms")
                else:
                    bad.append(f"{name} HTTP {resp.status}")
        except Exception as exc:                 # noqa: BLE001 - 网络问题一律降级
            bad.append(f"{name} {type(exc).__name__}")
    if not bad:
        return Check("网络", "ok", "、".join(ok))
    if ok:
        return Check("网络", "warn", "、".join(ok) + "；不通：" + "、".join(bad),
                     "部分平台会降级，页面照样能开")
    return Check("网络", "warn", "都连不上（现场断网？）",
                 "断网也能演：双击离线快照 demo/index.html，别赌 WiFi")


# ---------------------------------------------------------------- 汇总

def run_checks(port: int = 8791) -> list[Check]:
    checks: list[Check] = []
    checks.append(check_python())
    checks.append(check_deps())
    checks.append(check_browser())
    checks.append(check_state_dir())
    checks.extend(check_plugins())
    checks.append(check_database())
    checks.append(check_web())
    checks.extend(check_login())
    checks.append(check_port(port))
    checks.append(check_network())
    return checks


MARK = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]"}


def render(checks: list[Check]) -> int:
    width = max(len(c.name) for c in checks) if checks else 8
    for c in checks:
        print(f"{MARK.get(c.status, '[????]')} {c.name.ljust(width)}  {c.detail}")
        if c.hint and c.status != "ok":
            print(f"{' ' * 7}{' ' * width}  → {c.hint}")
    fails = [c for c in checks if c.status == "fail"]
    warns = [c for c in checks if c.status == "warn"]
    ok = [c for c in checks if c.status == "ok"]
    print()
    print(f"—— 结论 —— {len(ok)} 项就绪 / {len(warns)} 项降级 / {len(fails)} 项阻塞")
    if fails:
        print("阻塞项不修就演不全，先照着上面的 → 处理：")
        for c in fails:
            print(f"  · {c.name}：{c.detail}")
        return 1
    if warns:
        print("能演。降级项不影响主链路，心里有数就行。")
    else:
        print("全绿，直接开演。")
    return 0


def main(port: int = 8791) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    print(f"OneFeed 现场自检 · {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"仓库 {ROOT}")
    print()
    return render(run_checks(port))


if __name__ == "__main__":
    arg = 0
    if "--port" in sys.argv:
        try:
            arg = int(sys.argv[sys.argv.index("--port") + 1])
        except (IndexError, ValueError):
            arg = 0
    raise SystemExit(main(arg or 8791))
