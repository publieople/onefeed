"""专用 Chrome sidecar 与 CDP 连接。

方案 B：不再把 cookie 复制进 Playwright 自带的 headless Chromium，而是起一个
独立 user-data-dir 的 Chrome，用户在里面登录一次，登录态留在该 profile；
OneFeed 通过 CDP 接管它做采集和登录。这样设备信任、localStorage、服务端下发
的浏览器态都在同一个真实 profile 里，风控看到的也更接近真实用户。

配置（环境变量）：
- ONEFEED_BROWSER_CDP：CDP endpoint，例如 http://127.0.0.1:9223。未设置时默认
  http://127.0.0.1:9223；显式设为空字符串表示关闭。
- ONEFEED_BROWSER_PROFILE：sidecar 的 user-data-dir；默认 <状态目录>/chrome-profile。
- ONEFEED_CHROME_EXE：Chrome 可执行文件；默认自动查找 Windows Chrome/Edge。
- ONEFEED_CHROME_PORT：sidecar 端口，默认 9223（仅在 endpoint 未给端口时用）。
"""
from __future__ import annotations

import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Any

from .paths import state_root

DEFAULT_PORT = 9223


def endpoint() -> str | None:
    raw = os.environ.get("ONEFEED_BROWSER_CDP")
    if raw is None:
        # 默认走 CDP：不设变量时用本机 9223；显式空字符串才关闭。
        port = str(os.environ.get("ONEFEED_CHROME_PORT") or "").strip()
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            port = str(DEFAULT_PORT)
        return f"http://127.0.0.1:{port}"
    raw = raw.strip()
    if not raw:
        return None
    return raw.rstrip("/")


def enabled() -> bool:
    return endpoint() is not None


def profile_dir() -> Path:
    raw = str(os.environ.get("ONEFEED_BROWSER_PROFILE") or "").strip()
    return Path(raw) if raw else state_root() / "chrome-profile"


def find_chrome() -> str | None:
    raw = str(os.environ.get("ONEFEED_CHROME_EXE") or "").strip()
    if raw and os.path.exists(raw):
        return raw
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
        "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe",
        "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def _port(url: str) -> int:
    match = re.search(r":(\d+)(?:/|$)", url)
    return int(match.group(1)) if match else DEFAULT_PORT


def _alive(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url + "/json/version", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _win_path(path: str) -> str:
    """WSL 的 /mnt/<盘符>/... 转成 Windows 的 X:\\...，Chrome 只认后者。"""
    raw = str(path)
    if os.name == "nt":
        return raw
    match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", raw)
    if match:
        return match.group(1).upper() + ":\\" + match.group(2).replace("/", "\\")
    return raw


def _launch(url: str) -> None:
    exe = find_chrome()
    if not exe:
        raise RuntimeError(
            "找不到 Chrome/Edge：设置 ONEFEED_CHROME_EXE 指向 chrome.exe，"
            "或先手动启动专用 Chrome 并让它监听 CDP 端口。")
    profile = profile_dir()
    profile.mkdir(parents=True, exist_ok=True)
    port = _port(url)
    proxy = str(os.environ.get("ONEFEED_BROWSER_PROXY") or "").strip()
    args = [
        exe,
        f"--remote-debugging-port={port}",
        "--remote-debugging-address=127.0.0.1",
        f"--user-data-dir={_win_path(profile)}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--window-size=1440,940",
    ]
    if proxy:
        args.append(f"--proxy-server={proxy}")
    args.append("about:blank")
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)


def ensure(timeout: float = 20.0) -> str:
    """确保 sidecar 可达；可达直接返回 endpoint，不可达时尝试拉起并等待。"""
    url = endpoint()
    if not url:
        raise RuntimeError("CDP 模式已关闭（ONEFEED_BROWSER_CDP 为空字符串）")
    if _alive(url):
        return url
    _launch(url)
    deadline = time.time() + max(1.0, timeout)
    while time.time() < deadline:
        if _alive(url):
            return url
        time.sleep(0.4)
    raise RuntimeError(
        f"专用 Chrome 没有在 {url} 起来。检查 Chrome 是否被已有实例接管、"
        f"或手动启动：chrome.exe --remote-debugging-port={_port(url)} "
        f"--remote-debugging-address=127.0.0.1 --user-data-dir={_win_path(profile_dir())}")


def connect(pw) -> tuple[Any, Any]:
    """连上 sidecar，返回 (browser, context)。

    优先复用 Chrome 的默认 context；没有就新建。调用方只关自己开的 page，
    不要 close context/browser——它们属于用户的专用 Chrome。
    """
    url = ensure()
    browser = pw.chromium.connect_over_cdp(url)
    contexts = list(getattr(browser, "contexts", []) or [])
    ctx = contexts[0] if contexts else browser.new_context()
    return browser, ctx


def _domain_matches(domain: str, suffix: str) -> bool:
    """cookie 的 domain 是否属于某个站点（忽略前导点，匹配子域）。"""
    left = str(domain or "").strip().lower().lstrip(".")
    right = str(suffix or "").strip().lower().lstrip(".")
    if not left or not right:
        return False
    return left == right or left.endswith("." + right)


_COOKIE_CACHE: tuple[float, tuple[dict[str, Any], ...]] | None = None


def alive() -> bool:
    """sidecar 当前是否可达（不负责拉起）。"""
    url = endpoint()
    return bool(url and _alive(url))


def cookies(ttl: float = 2.0) -> list[dict[str, Any]]:
    """读 sidecar 当前 cookie；Chrome 没开就返回空，不主动拉起。"""
    global _COOKIE_CACHE
    if not endpoint():
        return []
    now = time.time()
    if _COOKIE_CACHE is not None and now - _COOKIE_CACHE[0] <= ttl:
        return [dict(c) for c in _COOKIE_CACHE[1]]
    if not alive():
        _COOKIE_CACHE = (now, ())
        return []
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            _browser, ctx = connect(pw)
            rows = tuple(dict(c) for c in ctx.cookies())
        _COOKIE_CACHE = (now, rows)
        return [dict(c) for c in rows]
    except Exception:
        return []


def cookie_names(domain: str | None = None, ttl: float = 2.0) -> set[str]:
    """sidecar 里的 cookie 名；domain 非空时只算该站点（含子域）。"""
    return {str(c.get("name")) for c in cookies(ttl=ttl)
            if c.get("name") and (not domain or _domain_matches(str(c.get("domain") or ""), domain))}


def _invalidate_cookies() -> None:
    global _COOKIE_CACHE
    _COOKIE_CACHE = None


def clear_cookies(domain: str | None = None) -> bool | None:
    """清掉 sidecar 里的登录 cookie；Chrome 没开就返回 False，不主动拉起。

    True = 确实清了；False = 没在运行，或没有匹配的 cookie；
    None = Chrome 连着但清理过程出错 —— 调用方不能把 None 说成「本来就没登录」。

    domain 非空时只清该站点（含子域）的 cookie。sidecar 是四个平台共用的，
    退出一个平台不能把其他平台的登录态一起清掉。
    """
    url = endpoint()
    if not url or not _alive(url):
        return False
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            _browser, ctx = connect(pw)
            if not domain:
                ctx.clear_cookies()
                _invalidate_cookies()
                return True
            cookies = [c for c in ctx.cookies()
                       if _domain_matches(str(c.get("domain") or ""), domain)]
            scopes = sorted({str(c.get("domain") or "") for c in cookies if c.get("domain")})
            for scope in scopes:
                ctx.clear_cookies(domain=scope)
            _invalidate_cookies()
            return bool(scopes)
    except Exception:
        return None


def launch_hint(error: str) -> str:
    low = str(error or "").lower()
    if "econnrefused" in low or "connection refused" in low or "connect_over_cdp" in low:
        return ("专用 Chrome 没连上：先启动它，或在设置里打开专用浏览器模式。"
                "（" + str(error)[:200] + "）")
    if "closed" in low:
        return "专用 Chrome 被关掉了；重新打开登录窗口即可。"
    return "专用浏览器出错：" + str(error)[:240]
