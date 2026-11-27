"""登录闭环：宿主开一个自己的 Chrome 窗口，用户自己扫码/输密码，宿主只拿 cookie。

边界要说清楚（前端也会这么写）：
- 窗口用的是独立 user-data-dir（<状态目录>/login/<插件>），不碰你日常浏览器的 profile；
- 宿主只读 cookie，不读历史、不读密码；cookie 写到 <状态目录>/cookies/<插件>.json；
- 插件永远拿不到明文 cookie，只能在宿主代发请求时被动带上。

为什么用 Playwright 的持久上下文，而不是自己 Popen 一个 Chrome：
在 uv 管理的虚拟环境里直接 Popen Chrome 会让浏览器秒退（退出码 0x80000003），
而 Playwright 自带的驱动进程能把窗口正常拉起来；顺带还能直接读 cookie，
不用再折腾 CDP 端口。Playwright 的 sync API 不能跨线程用，
所以每个登录窗口都有一个自己的后台线程，cookie 轮询和关窗都在那个线程里完成。
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

from plugin_runtime import browser_cdp
from plugin_runtime.paths import state_root

# 每个平台的登录页 + cookie 判据。判据只认"登录后才出现"的 cookie，
# 别用 web_session：小红书游客态也会带 web_session（前面踩过）。
SPECS: dict[str, dict[str, Any]] = {
    "xiaohongshu": {
        "label": "小红书",
        "url": "https://www.xiaohongshu.com/explore",
        "domain": ".xiaohongshu.com",
        "cookies": ("id_token",),
        "impact": "小红书首页推荐需要登录，未登录只能拿到公开页。",
    },
    "douyin": {
        "label": "抖音",
        "url": "https://www.douyin.com/",
        "domain": ".douyin.com",
        "cookies": ("sessionid", "sessionid_ss"),
        "impact": "抖音未登录也能采到网页推荐流；登录后是更贴近你自己的那一条。",
    },
    "zhihu": {
        "label": "知乎",
        "url": "https://www.zhihu.com/",
        "domain": ".zhihu.com",
        "cookies": ("z_c0",),
        "impact": "知乎首页 2026 年起对游客直接跳登录页，推荐流和关注流都要求登录态。",
    },
}

# 登录态由外部 CLI 管理的平台，宿主不开窗口，只负责说清楚怎么弄。
CLI_SPECS: dict[str, dict[str, str]] = {
    "bilibili": {
        "label": "B 站",
        "hint": "B 站登录由本机 bili CLI 管理：终端执行 bili login 扫码，凭证 CLI 自己保存。",
        "command": "bili login",
    },
}

MAX_WAIT_SEC = 600      # 窗口最多替你守 10 分钟
LAUNCH_WAIT_SEC = 60    # 等浏览器出来的上限
POLL_SEC = 2.0

_SESSIONS: dict[str, "_Session"] = {}
_LOCK = threading.Lock()


def _login_dir() -> Path:
    path = state_root() / "login"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cookie_path(plugin_id: str) -> Path:
    return state_root() / "cookies" / f"{plugin_id}.json"


def _profile_dir(plugin_id: str) -> Path:
    return _login_dir() / plugin_id


def _write_cookie_file(plugin_id: str, cookies: list[dict[str, Any]]) -> Path:
    keep = []
    for c in cookies:
        name = str(c.get("name") or "")
        if not name:
            continue
        keep.append({
            "name": name, "value": c.get("value", ""),
            "domain": c.get("domain", ""), "path": c.get("path", "/"),
            "expires": c.get("expires", -1),
            "httpOnly": bool(c.get("httpOnly")),
            "secure": bool(c.get("secure")),
            "sameSite": c.get("sameSite", "Lax"),
        })
    path = _cookie_path(plugin_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"plugin": plugin_id, "saved_at": int(time.time()),
                                "source": "browser-login", "cookies": keep},
                               ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _cookie_names(plugin_id: str) -> list[str]:
    path = _cookie_path(plugin_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("cookies") if isinstance(data, dict) and "cookies" in data else data
    if isinstance(raw, dict):
        return list(raw.keys())
    if isinstance(raw, list):
        return [str(c.get("name")) for c in raw if isinstance(c, dict) and c.get("name")]
    return []


def _launch_hint(error: str) -> str:
    """把 Playwright 的原始报错翻成能照着做的一句话。"""
    low = error.lower()
    if "executable doesn't exist" in low or "channel" in low and "not found" in low:
        return ("本机没找到 Chrome：登录窗口用的是系统装的 Chrome，不是 Playwright 自带的 Chromium。"
                "装一个 Chrome 再点一次「打开登录窗口」。" + "（" + error[:160] + "）")
    if "eperm" in low or "mkdtemp" in low:
        return ("临时目录写不进去，Playwright 起不来。把 TMP/TEMP 指到可写目录后重启 OneFeed。"
                + "（" + error[:160] + "）")
    return "浏览器没起来：" + error


class _Session:
    """一个登录窗口 = 一个后台线程 + 一个 Playwright 持久上下文。"""

    def __init__(self, plugin_id: str, spec: dict[str, Any]) -> None:
        self.plugin_id = plugin_id
        self.spec = spec
        # CDP 模式下 profile 属于专用 Chrome，不再是每个插件自己的登录窗口目录。
        self.profile = browser_cdp.profile_dir() if browser_cdp.enabled() else _profile_dir(plugin_id)
        self.state = "opened"
        self.message = "正在打开登录窗口…"
        self.cookies = 0
        self.page_url = str(spec["url"])
        self.path: str | None = None
        self.cookie = ""
        self.error = ""
        self.started_at = int(time.time())
        self.stop = threading.Event()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self._run, name=f"login-{plugin_id}", daemon=True)

    # ---- 线程内 ----
    def _run(self) -> None:
        if browser_cdp.enabled():
            self._run_cdp()
            return

        from plugin_runtime.paths import ensure_temp_env
        ensure_temp_env()          # Playwright 的临时目录必须可写
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                try:
                    ctx = pw.chromium.launch_persistent_context(
                        str(self.profile),
                        channel="chrome",
                        headless=False,
                        viewport={"width": 1280, "height": 900},
                        args=["--no-first-run", "--no-default-browser-check",
                              "--window-size=1280,940"],
                    )
                except Exception as exc:              # 浏览器没起来
                    self.state = "error"
                    self.error = f"{type(exc).__name__}: {exc}"[:300]
                    self.message = _launch_hint(self.error)
                    self.ready.set()
                    return

                self.state = "waiting"
                self.message = f"窗口已打开，请在窗口里登录{self.spec['label']}"
                self.ready.set()
                try:
                    self._poll(ctx)
                finally:
                    try:
                        ctx.close()
                    except Exception:
                        pass
        except Exception as exc:                      # Playwright 自己起不来
            if self.state not in ("ok", "closed"):
                self.state = "error"
                self.error = f"{type(exc).__name__}: {exc}"[:300]
                self.message = "登录窗口出错：" + self.error
        finally:
            self.ready.set()

    def _run_cdp(self) -> None:
        """方案 B：连接专用 Chrome，登录窗口就是它自己的一个标签页。

        登录态留在 sidecar 的 user-data-dir 里；这里不启动新浏览器、不复制 cookie，
        拿到目标 cookie 后仍写一份状态文件，供设置页显示登录状态和兼容旧逻辑。
        """
        from plugin_runtime.paths import ensure_temp_env
        ensure_temp_env()
        page = None
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as pw:
                try:
                    browser_cdp.ensure()
                    _browser, ctx = browser_cdp.connect(pw)
                except Exception as exc:
                    self.state = "error"
                    self.error = f"{type(exc).__name__}: {exc}"[:300]
                    self.message = browser_cdp.launch_hint(self.error)
                    self.ready.set()
                    return

                self.state = "waiting"
                label = str(self.spec["label"])
                self.message = f"请在专用 Chrome 里登录{label}（登录态会留在该浏览器）"
                self.ready.set()
                try:
                    page = ctx.new_page()
                    try:
                        page.bring_to_front()
                    except Exception:
                        pass
                    self._poll(ctx, page)
                finally:
                    if page is not None:
                        try:
                            page.close()
                        except Exception:
                            pass
        except Exception as exc:
            if self.state not in ("ok", "closed"):
                self.state = "error"
                self.error = f"{type(exc).__name__}: {exc}"[:300]
                self.message = "登录窗口出错：" + self.error
        finally:
            self.ready.set()

    def _poll(self, ctx, page=None) -> None:
        if page is None:
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
            except Exception:
                page = None
        try:
            if page is None:
                page = ctx.new_page()
            try:
                page.bring_to_front()
                page.goto(str(self.spec["url"]), wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass                                  # 页面慢/被风控拦，让用户自己在窗口里点
        except Exception:
            page = None

        domain = str(self.spec["domain"])
        wanted = {str(n) for n in self.spec["cookies"]}
        deadline = time.time() + MAX_WAIT_SEC
        while not self.stop.is_set():
            if time.time() > deadline:
                self.state = "error"
                self.message = f"等了 {MAX_WAIT_SEC // 60} 分钟没等到登录 cookie，窗口已关掉，重试一次"
                return
            try:
                cookies = ctx.cookies()
            except Exception as exc:
                text = str(exc)
                self.state = "closed"
                self.message = ("登录窗口被关掉了" if "closed" in text.lower()
                               else f"读 cookie 失败：{text}"[:300])
                return
            scoped = [c for c in cookies if str(c.get("domain") or "").endswith(domain)]
            self.cookies = len(scoped)
            try:
                if page is not None:
                    self.page_url = page.url or self.page_url
            except Exception:
                page = None
            probe = next((c for c in scoped
                          if str(c.get("name")) in wanted and str(c.get("value") or "")), None)
            if probe is not None:
                path = _write_cookie_file(self.plugin_id, scoped)
                self.path = str(path)
                self.cookie = str(probe.get("name"))
                self.state = "ok"
                self.message = f"已拿到 {len(scoped)} 个 cookie（含 {probe.get('name')}），窗口已关闭"
                return
            time.sleep(POLL_SEC)


def _snapshot(session: _Session) -> dict[str, Any]:
    data: dict[str, Any] = {
        "plugin": session.plugin_id,
        "state": session.state,
        "message": session.message,
        "cookies": session.cookies,
        "url": session.page_url,
        "profile": str(session.profile),
        "started_at": session.started_at,
    }
    if session.path:
        data["path"] = session.path
    if session.cookie:
        data["cookie"] = session.cookie
    return data


def start(plugin_id: str) -> dict[str, Any]:
    """打开登录窗口；已经开着就直接复用，不重复弹窗。"""
    spec = SPECS.get(plugin_id)
    if spec is None:
        raise KeyError(f"{plugin_id} 没有内置登录流程")

    with _LOCK:
        live = _SESSIONS.get(plugin_id)
        if live is not None and live.thread.is_alive() and live.state in ("opened", "waiting"):
            return {**_snapshot(live), "reused": True}
        session = _Session(plugin_id, spec)
        _SESSIONS[plugin_id] = session
        session.thread.start()

    if not session.ready.wait(LAUNCH_WAIT_SEC):
        raise RuntimeError("登录窗口迟迟没出来；关掉残留的窗口再试一次")
    if session.state == "error":
        raise RuntimeError(session.error or "登录窗口没起来")
    return {**_snapshot(session), "reused": False}


def check(plugin_id: str) -> dict[str, Any]:
    """查登录进度：窗口开着 → waiting；拿到 cookie → ok；窗口被关 → closed。"""
    spec = SPECS.get(plugin_id)
    if spec is None:
        raise KeyError(f"{plugin_id} 没有内置登录流程")

    session = _SESSIONS.get(plugin_id)
    if session is not None:
        data = _snapshot(session)
        if session.state in ("opened", "waiting"):
            if not session.thread.is_alive():
                data["state"] = "closed"
                data["message"] = "登录窗口已经关了；重新打开一次就行"
        return data

    if browser_cdp.enabled():
        names = browser_cdp.cookie_names(str(spec["domain"]))
        if any(n in set(spec["cookies"]) for n in names):
            return {"plugin": plugin_id, "state": "ok", "cookies": len(names),
                    "path": str(_cookie_path(plugin_id)),
                    "message": f"已登录（专用 Chrome 里有 {len(names)} 个 cookie）"}
        if not browser_cdp.alive():
            return {"plugin": plugin_id, "state": "idle", "cookies": len(names),
                    "message": "专用 Chrome 没在运行；打开登录窗口会沿用已保存的 profile"}
        return {"plugin": plugin_id, "state": "idle", "cookies": len(names),
                "message": "专用 Chrome 里还没登录；打开登录窗口扫码"}

    names = _cookie_names(plugin_id)
    if any(n in set(spec["cookies"]) for n in names):
        return {"plugin": plugin_id, "state": "ok", "cookies": len(names),
                "path": str(_cookie_path(plugin_id)), "message": f"已登录（{len(names)} 个 cookie）"}
    return {"plugin": plugin_id, "state": "idle", "cookies": len(names),
            "message": "还没打开登录窗口"}


def session_state(plugin_id: str) -> str | None:
    session = _SESSIONS.get(plugin_id)
    return session.state if session is not None else None


def logout(plugin_id: str) -> dict[str, Any]:
    removed = []
    with _LOCK:
        session = _SESSIONS.pop(plugin_id, None)
    if session is not None:
        session.stop.set()
        session.thread.join(8)
        removed.append("登录窗口")

    cookie_path = _cookie_path(plugin_id)
    if cookie_path.exists():
        cookie_path.unlink()
        removed.append("cookie")

    if browser_cdp.enabled():
        spec = SPECS.get(plugin_id)
        if spec and browser_cdp.clear_cookies(str(spec["domain"])):
            removed.append("专用 Chrome cookie")
        return {"plugin": plugin_id, "removed": removed,
                "message": "已退出：状态文件与专用 Chrome 的登录 cookie 都清了" if removed else "本来就没有登录态"}

    profile = _profile_dir(plugin_id)
    if profile.exists():
        for attempt in range(5):        # 窗口刚关时文件还被占着，等一下重试
            try:
                shutil.rmtree(profile)
                removed.append("登录 profile")
                break
            except OSError:
                time.sleep(0.4)
    return {"plugin": plugin_id, "removed": removed,
            "message": "已退出：cookie 与登录窗口 profile 都删了" if removed else "本来就没有登录态"}


def describe(plugin_id: str) -> dict[str, Any]:
    """给 /api/auth/<id> 用的静态说明，不触网。"""
    if plugin_id in SPECS:
        spec = SPECS[plugin_id]
        return {"plugin": plugin_id, "can_login": True, "label": spec["label"],
                "login_url": spec["url"], "impact": spec["impact"],
                "cookie_names": list(spec["cookies"])}
    if plugin_id in CLI_SPECS:
        spec = CLI_SPECS[plugin_id]
        return {"plugin": plugin_id, "can_login": False, "cli": True,
                "label": spec["label"], "hint": spec["hint"], "command": spec["command"]}
    return {"plugin": plugin_id, "can_login": False}