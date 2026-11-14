"""宿主能力层：插件能做的全部事情都从这里过。

设计口径：插件拿到的是"动词"（发一个 http、跑一条白名单命令、抓一次页面），
拿不到"名词"（文件句柄、socket、cookie 明文、其他插件的数据）。

所有能力都是同步实现，因为它们在**子进程**里跑，不在宿主事件循环里。
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .manifest import Manifest
from .paths import browser_profile, ensure_temp_env, plugin_dir, state_root

MAX_BODY_BYTES = 5 * 1024 * 1024     # http 响应体上限 5MB
MAX_HTML_CHARS = 2_000_000
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

# 只保留与网络/编码相关的变量：本机 NO_PROXY 含 [::1]，任何读环境代理的库都会崩
SAFE_ENV_KEYS = ("PATH", "PATHEXT", "SystemRoot", "windir", "COMSPEC", "USERPROFILE",
                 "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
                 "TEMP", "TMP", "HOMEDRIVE", "HOMEPATH", "NUMBER_OF_PROCESSORS",
                 "PROCESSOR_ARCHITECTURE", "PYTHONUTF8", "PYTHONIOENCODING")
PROXY_CANDIDATES = ("", "http://127.0.0.1:7890", "http://127.0.0.1:10809")


def clean_env() -> dict[str, str]:
    """子进程用的环境：白名单 + 强制 UTF-8，不带任何代理变量。"""
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def clamp(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if not isinstance(value, str):
        return 0
    s = value.strip().replace(",", "")
    mult = 1
    if s.endswith("万"):
        mult, s = 10_000, s[:-1]
    elif s.endswith("亿"):
        mult, s = 100_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def _is_public_http(url: str) -> bool:
    """只允许 http(s)，且不允许指向本机/内网（插件不该能扫宿主内网）。"""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    host = parsed.hostname
    if host in ("localhost",) or host.endswith(".local"):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return True  # 解析不了就交给请求阶段报错
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    return True


class Capabilities:
    """一个插件实例的能力集合（每次调用新建，无跨调用状态）。"""

    def __init__(self, manifest: Manifest, settings: dict[str, Any] | None = None,
                 demo: bool = False, logger=None):
        self.manifest = manifest
        self.settings = {**manifest.setting_defaults(), **(settings or {})}
        self.demo = demo
        self.state_dir = plugin_dir(manifest.id)
        self._logger = logger
        self._browser_ctx = None
        self._playwright = None

    # ------------------------------------------------------------ 入口
    def log(self, level: str, message: str) -> None:
        line = f"[{self.manifest.id}] {message}"
        if self._logger:
            self._logger(level, line)
        else:
            print(line, file=sys.stderr)

    def handle(self, raw: str) -> str:
        """JS 侧唯一入口：入参 {"cap": "...", ...}，出参 JSON。"""
        try:
            req = json.loads(raw)
        except json.JSONDecodeError as exc:
            return json.dumps({"ok": False, "error": f"bad capability payload: {exc}"})
        cap = req.get("cap")
        try:
            handler = {
                "http": self._http,
                "cli": self._cli,
                "browser": self._browser,
                "storage": self._storage,
                "cache": self._cache,
                "settings": self._settings,
            }.get(str(cap))
            if handler is None:
                raise ValueError(f"未知能力: {cap}")
            if cap == "http" and "http" not in self.manifest.capabilities:
                raise PermissionError("插件未声明 http 能力")
            if cap == "cli" and "cli" not in self.manifest.capabilities:
                raise PermissionError("插件未声明 cli 能力")
            if cap == "browser" and "browser" not in self.manifest.capabilities:
                raise PermissionError("插件未声明 browser 能力")
            return json.dumps({"ok": True, "data": handler(req)}, ensure_ascii=False)
        except Exception as exc:  # 能力层异常一律转成 JS 侧可读错误
            return json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"},
                              ensure_ascii=False)

    # ------------------------------------------------------------ http
    def _http(self, req: dict[str, Any]) -> dict[str, Any]:
        url = str(req.get("url") or "")
        if not url:
            raise ValueError("http.request 缺少 url")
        query = req.get("query")
        if query:
            sep = "&" if "?" in url else "?"
            url = url + sep + urllib.parse.urlencode(query, doseq=True)

        if not _is_public_http(url):
            raise PermissionError(f"拒绝请求非公网地址: {url}")

        headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9"}
        headers.update({str(k): str(v) for k, v in (req.get("headers") or {}).items()})

        body = req.get("body")
        data: bytes | None = None
        if body is not None:
            if isinstance(body, (dict, list)):
                data = json.dumps(body, ensure_ascii=False).encode()
                headers.setdefault("Content-Type", "application/json")
            else:
                data = str(body).encode()
        method = str(req.get("method") or ("POST" if data is not None else "GET")).upper()

        if req.get("credential") == "self":
            self._inject_cookie(headers)

        timeout = min(float(req.get("timeoutMs") or 15000) / 1000.0, 30.0)
        self.log("info", f"http {method} {url[:120]}")

        last: Exception | None = None
        # 直连优先；失败再试本机常见代理（Clash 7890 / v2ray 10809）
        for proxy in PROXY_CANDIDATES:
            handlers = {"http": proxy, "https": proxy} if proxy else {}
            opener = urllib.request.build_opener(urllib.request.ProxyHandler(handlers))
            request = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with opener.open(request, timeout=timeout) as resp:
                    raw = resp.read(MAX_BODY_BYTES + 1)
                    text = raw[:MAX_BODY_BYTES].decode("utf-8", "replace")
                    if len(raw) > MAX_BODY_BYTES:
                        raise ValueError("响应体超过 5MB，已截断拒绝")
                    return {"status": resp.status, "text": text,
                            "headers": {k.lower(): v for k, v in resp.headers.items()}}
            except urllib.error.HTTPError as exc:
                text = exc.read()[:MAX_BODY_BYTES].decode("utf-8", "replace")
                return {"status": exc.code, "text": text,
                        "headers": {k.lower(): v for k, v in (exc.headers or {}).items()}}
            except Exception as exc:  # 直连被墙/超时，换代理
                last = exc
                continue
        raise RuntimeError(f"请求失败（直连与代理均不通）: {type(last).__name__}: {last}")

    def _inject_cookie(self, headers: dict[str, str]) -> None:
        """credential=self：用插件自己配置的 cookie（宿主读取，明文不出宿主）。"""
        raw = self.settings.get("cookie")
        if raw:
            headers["Cookie"] = str(raw)
            return
        cookie_file = self.settings.get("cookieFile")
        if not cookie_file:
            return
        path = Path(os.path.expanduser(str(cookie_file)))
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict) and isinstance(data.get("cookies"), list):
            pairs = [f"{c.get('name')}={c.get('value')}" for c in data["cookies"] if c.get("name")]
            if pairs:
                headers["Cookie"] = "; ".join(pairs)
        elif isinstance(data, dict):
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in data.items())

    # ------------------------------------------------------------ cli
    def _cli(self, req: dict[str, Any]) -> dict[str, Any]:
        argv = req.get("argv")
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise ValueError("cli.run 需要非空字符串数组 argv")
        if not self._cli_allowed(argv):
            raise PermissionError(
                f"命令不在白名单内: {argv[0]}（允许 {[' '.join(a) for a in self.manifest.cli_allow]}）")
        timeout = min(float(req.get("timeoutMs") or 60000) / 1000.0, 120.0)
        self.log("info", "cli " + " ".join(argv)[:160])
        exe = argv[0]
        resolved = _which(exe) or exe
        proc = subprocess.run([resolved, *argv[1:]], capture_output=True, timeout=timeout,
                              env=clean_env(), cwd=str(Path.home()))
        return {
            "code": proc.returncode,
            "stdout": proc.stdout.decode("utf-8", "replace"),
            "stderr": proc.stderr.decode("utf-8", "replace"),
        }

    def _cli_allowed(self, argv: list[str]) -> bool:
        name = Path(argv[0]).name
        for entry in self.manifest.cli_allow:
            if not entry:
                continue
            if Path(entry[0]).name != name:
                continue
            # entry 后续段是参数前缀（可选）
            if argv[1:1 + len(entry) - 1] == entry[1:]:
                return True
        return False

    # ------------------------------------------------------------ browser
    def _browser(self, req: dict[str, Any]) -> dict[str, Any]:
        """粗粒度抓取：打开一个页面、等指定响应、滚几屏、把 JSON body 交回去。

        不给插件长生命周期 page 句柄——用完即销毁，避免插件持有会话。
        """
        from playwright.sync_api import sync_playwright

        patterns = [re.compile(p) for p in (req.get("patterns") or [])]
        if not patterns:
            raise ValueError("browser.capture 需要至少一个 patterns（正则）")
        url = str(req.get("url") or "")
        if not url.startswith(("http://", "https://")):
            raise ValueError("browser.capture 需要 http(s) url")

        scroll = req.get("scroll") or {}
        scroll_times = min(int(scroll.get("times") or 0), 10)
        dy = int(scroll.get("dy") or 2400)
        interval = min(int(scroll.get("intervalMs") or 800), 5000)
        timeout_ms = min(int(req.get("timeoutMs") or 45000), 90000)
        settle_ms = min(int(req.get("settleMs") or 2500), 15000)
        want_html = bool(req.get("html"))

        profile = self.settings.get("browserProfile") or str(
            browser_profile(self.manifest.id))
        Path(profile).mkdir(parents=True, exist_ok=True)

        bodies: list[dict[str, Any]] = []

        def on_response(resp) -> None:
            if not any(p.search(resp.url) for p in patterns):
                return
            try:
                bodies.append({"url": resp.url, "json": resp.json()})
            except Exception:
                try:
                    bodies.append({"url": resp.url, "text": resp.text()})
                except Exception:
                    bodies.append({"url": resp.url, "json": None})

        # playwright 的 node driver 只认 TEMP/TMP 找临时目录，而受限环境里
        # 用户级 Temp 未必可写，所以显式指到自有 scratch 目录。
        ensure_temp_env()

        self.log("info", f"browser {url[:120]}")
        pw = sync_playwright().start()
        ctx = None
        try:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                executable_path=_find_chrome(),
                headless=bool(req.get("headless", True)),
                locale="zh-CN",
                viewport={"width": 1440, "height": 900},
                user_agent=UA,
                args=["--disable-blink-features=AutomationControlled", "--window-size=1440,900"],
            )
            self._inject_browser_cookies(ctx)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            deadline = time.time() + timeout_ms / 1000.0
            page.wait_for_timeout(settle_ms)
            for _ in range(scroll_times):
                if bodies and req.get("stopWhenMatched", True):
                    break
                if time.time() > deadline:
                    break
                page.mouse.wheel(0, dy)
                page.wait_for_timeout(interval)

            remaining = max(0.0, deadline - time.time())
            while not bodies and remaining > 0:
                page.wait_for_timeout(min(1000, int(remaining * 1000)))
                remaining = max(0.0, deadline - time.time())

            out: dict[str, Any] = {"url": page.url, "responses": bodies[:20]}
            if want_html:
                out["html"] = page.content()[:MAX_HTML_CHARS]
            return out
        finally:
            try:
                if ctx is not None:
                    ctx.close()
            finally:
                pw.stop()

    def _cookie_path(self) -> Path | None:
        """cookie 文件查找顺序：settings.cookieFile → 状态目录 cookies/<plugin_id>.json。

        后者是客户端登录成功后该写的地方（宿主与客户端约定，插件看不到内容）。
        """
        raw = self.settings.get("cookieFile")
        if raw:
            path = Path(os.path.expanduser(str(raw)))
            if path.is_file():
                return path
        fallback = state_root() / "cookies" / f"{self.manifest.id}.json"
        return fallback if fallback.is_file() else None

    def _inject_browser_cookies(self, ctx) -> None:
        path = self._cookie_path()
        if path is None:
            self.log("warn", "没有 cookie 文件，按未登录抓取")
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        cookies = data.get("cookies") if isinstance(data, dict) else None
        if isinstance(cookies, dict):   # 兼容 {name: value} 形式
            cookies = [{"name": k, "value": v} for k, v in cookies.items()]
        if not isinstance(cookies, list):
            return
        default_domain = str(self.settings.get("cookieDomain") or ".douyin.com")
        prepared = []
        for c in cookies:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            prepared.append({
                "name": c["name"], "value": c.get("value", ""),
                "domain": c.get("domain") or default_domain,
                "path": c.get("path") or "/",
                "httpOnly": bool(c.get("httpOnly")),
                "secure": bool(c.get("secure")),
                "sameSite": c.get("sameSite") or "Lax",
            })
        if prepared:
            try:
                ctx.add_cookies(prepared)
                self.log("info", f"注入 {len(prepared)} 个 cookie")
            except Exception as exc:
                self.log("warn", f"cookie 注入失败: {exc}")

    # ------------------------------------------------------------ storage / cache / settings
    def _read_state(self, name: str) -> dict[str, Any]:
        path = self.state_dir / name
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_state(self, name: str, data: dict[str, Any]) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _storage(self, req: dict[str, Any]) -> dict[str, Any]:
        op = req.get("op")
        store = self._read_state("storage.json")
        key = str(req.get("key") or "")
        if op == "get":
            return {"value": store.get(key)}
        if op == "set":
            store[key] = req.get("value")
            self._write_state("storage.json", store)
            return {"value": True}
        if op == "delete":
            store.pop(key, None)
            self._write_state("storage.json", store)
            return {"value": True}
        if op == "keys":
            return {"value": sorted(store)}
        raise ValueError(f"未知 storage 操作: {op}")

    def _cache(self, req: dict[str, Any]) -> dict[str, Any]:
        op = req.get("op")
        store = self._read_state("cache.json")
        now = int(time.time())
        key = str(req.get("key") or "")
        if op == "get":
            row = store.get(key)
            if not row or int(row.get("exp") or 0) < now:
                return {"value": None}
            return {"value": row.get("value")}
        if op == "set":
            ttl = int(req.get("ttlSec") or 300)
            store[key] = {"value": req.get("value"), "exp": now + ttl}
            self._write_state("cache.json", store)
            return {"value": True}
        raise ValueError(f"未知 cache 操作: {op}")

    def _settings(self, req: dict[str, Any]) -> dict[str, Any]:
        key = str(req.get("key") or "")
        declared = {s["key"]: s for s in self.manifest.settings if s.get("key")}
        spec = declared.get(key) or {}
        value = self.settings.get(key)
        if spec.get("secret"):
            return {"value": None, "has": bool(value)}
        return {"value": value}


def _which(name: str) -> str | None:
    from shutil import which
    return which(name) or which(name + ".exe")


def _find_chrome() -> str | None:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None
