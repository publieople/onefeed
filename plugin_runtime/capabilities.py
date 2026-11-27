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
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import browser_cdp
from .manifest import Manifest
from .paths import browser_profile, ensure_temp_env, plugin_dir, state_root

MAX_BODY_BYTES = 5 * 1024 * 1024     # http 响应体上限 5MB
MAX_HTML_CHARS = 2_000_000
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

# 只保留与网络/编码相关的变量：本机 NO_PROXY 含 [::1]，任何读环境代理的库都会崩。
# ONEFEED_* 是宿主自己的运行配置：不带下去，worker 会退回 ~/.onefeed 和自建 headless
# Chromium，而不是当前实例的状态目录与正在登录的 sidecar Chrome。
SAFE_ENV_KEYS = ("PATH", "PATHEXT", "SystemRoot", "windir", "COMSPEC", "USERPROFILE",
                 "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA",
                 "TEMP", "TMP", "HOMEDRIVE", "HOMEPATH", "NUMBER_OF_PROCESSORS",
                 "PROCESSOR_ARCHITECTURE", "PYTHONUTF8", "PYTHONIOENCODING",
                 "ONEFEED_HOME", "ONEFEED_BROWSER_CDP", "ONEFEED_BROWSER_PROFILE",
                 "ONEFEED_CHROME_PORT", "ONEFEED_CHROME_EXE", "ONEFEED_BROWSER_PROXY")
PROXY_CANDIDATES = ("", "http://127.0.0.1:7890", "http://127.0.0.1:10809")

# Chrome 的 user-data-dir 一个进程独占：详情和评论并发时会互相把对方顶掉，
# 所以这个进程里的浏览器操作排队执行。
BROWSER_LOCK = threading.Lock()

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - 本机只有 Windows
    msvcrt = None


class _ProfileGuard:
    """跨进程排队：同一个 Chrome user-data-dir 只让一个会话开。

    插件各自跑在 worker 子进程里，进程内的锁拦不住它们，所以用 profile 目录
    里的一把文件锁——拿到锁的开浏览器，另一个在门口等。
    """

    def __init__(self, profile: str | Path):
        self.profile = Path(profile)
        self.fh: Any = None

    def acquire(self, wait_s: float = 120.0) -> None:
        self.profile.mkdir(parents=True, exist_ok=True)
        self.fh = open(self.profile / ".browser.lock", "a+b")
        deadline = time.time() + wait_s
        while True:
            try:
                if msvcrt is not None:
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except OSError:
                if time.time() > deadline:
                    raise TimeoutError("另一个浏览器会话占着 profile，等它超时了")
                time.sleep(0.4)

    def release(self) -> None:
        if self.fh is None:
            return
        try:
            self.fh.seek(0)
            if msvcrt is not None:
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            self.fh.close()
            self.fh = None

# 具名提取器：宿主写死，插件只能点名调用，不能塞自己的 JS。
# 页面里的 __INITIAL_STATE__ 带 undefined / new Map([]) 这类字面量，服务端拿 HTML 解析不了，
# 必须在浏览器里 evaluate 出来再当 JSON 交回去。
EXTRACTORS: dict[str, dict[str, Any]] = {
    "xhs.note": {
        "hosts": ("xiaohongshu.com",),
        "settleMs": 3500,
        "js": r"""() => {
  try {
    const st = window.__INITIAL_STATE__ || {};
    const note = st.note || {};
    const map = note.noteDetailMap || note.note_detail_map || {};
    const keys = Object.keys(map);
    if (!keys.length) return { ok: false, reason: 'no_note_map', href: location.href };
    const first = map[keys[0]] || {};
    const card = first.note || first.noteCard || {};
    const video = card.video || {};
    const media = video.media || {};
    const stream = media.stream || {};
    const streams = [];
    Object.keys(stream).forEach(function (codec) {
      const list = stream[codec];
      if (!Array.isArray(list)) return;
      list.forEach(function (s) {
        if (s && s.masterUrl) streams.push({ codec: codec, url: String(s.masterUrl), quality: String(s.qualityType || ''), format: String(s.format || '') });
      });
    });
    const images = [];
    (card.imageList || []).forEach(function (img) {
      if (!img) return;
      const info = (img.infoList || []).filter(function (i) { return i && i.imageScene === 'WB_DFT'; })[0] || {};
      const url = String(info.url || img.urlDefault || img.urlPre || img.url || '');
      if (url) images.push(url);
    });
    const user = card.user || {};
    const interact = card.interactInfo || {};
    const capa = video.capa || {};
    return {
      ok: true,
      id: String(first.noteId || card.noteId || ''),
      title: String(card.title || ''),
      desc: String(card.desc || ''),
      type: String(card.type || ''),
      ipLocation: String(card.ipLocation || ''),
      time: Number(card.time || 0),
      user: { name: String(user.nickname || ''), id: String(user.userId || ''), avatar: String(user.avatar || '') },
      interact: { like: String(interact.likedCount || ''), comment: String(interact.commentCount || ''), collect: String(interact.collectedCount || ''), share: String(interact.shareCount || '') },
      images: images,
      duration: Number(capa.duration || 0),
      streams: streams,
      tags: (card.tagList || []).map(function (t) { return String(t && t.name || ''); }).filter(Boolean)
    };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 300) }; }
}""",
    },
    "zhihu.question": {
        "hosts": ("zhihu.com",),
        "settleMs": 4000,
        "js": r"""() => {
  try {
    const el = document.getElementById('js-initialData');
    if (!el) return { ok: false, reason: 'no_initial_data', href: location.href };
    const data = JSON.parse(el.textContent || '{}');
    const state = data.initialState || {};
    const ents = state.entities || {};
    const questions = ents.questions || {};
    const qKeys = Object.keys(questions);
    const q = qKeys.length ? questions[qKeys[0]] : {};
    const answers = ents.answers || {};
    const rows = [];
    Object.keys(answers).forEach(function (key) {
      const a = answers[key] || {};
      const author = a.author || {};
      rows.push({
        id: String(a.id || key),
        author: String(author.name || ''),
        authorUrl: String(author.urlToken || ''),
        voteup: Number(a.voteupCount || 0),
        comment: Number(a.commentCount || 0),
        createdTime: Number(a.createdTime || 0),
        content: String(a.content || '').slice(0, 60000)
      });
    });
    rows.sort(function (x, y) { return y.voteup - x.voteup; });
    return {
      ok: true,
      question: {
        id: String(q.id || ''),
        title: String(q.title || ''),
        detail: String(q.detail || '').slice(0, 20000),
        answerCount: Number(q.answerCount || 0),
        followerCount: Number(q.followerCount || 0),
        commentCount: Number(q.commentCount || 0)
      },
      answers: rows.slice(0, 5)
    };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 300) }; }
}""",
    },
    "zhihu.article": {
        "hosts": ("zhihu.com",),
        "settleMs": 4000,
        "js": r"""() => {
  try {
    const el = document.getElementById('js-initialData');
    if (!el) return { ok: false, reason: 'no_initial_data', href: location.href };
    const data = JSON.parse(el.textContent || '{}');
    const ents = ((data.initialState || {}).entities) || {};
    const articles = ents.articles || {};
    const keys = Object.keys(articles);
    if (!keys.length) return { ok: false, reason: 'no_article', href: location.href };
    const a = articles[keys[0]] || {};
    const author = a.author || {};
    return {
      ok: true,
      id: String(a.id || keys[0]),
      title: String(a.title || ''),
      content: String(a.content || '').slice(0, 60000),
      author: String(author.name || ''),
      avatar: String(author.avatarUrl || author.avatar_url || ''),
      voteup: Number(a.voteupCount || 0),
      comment: Number(a.commentCount || 0),
      created: Number(a.created || 0),
      updated: Number(a.updated || 0)
    };
  } catch (e) { return { ok: false, reason: String(e).slice(0, 300) }; }
}""",
    },
}


def clean_env() -> dict[str, str]:
    """子进程用的环境：白名单 + 强制 UTF-8，不带任何代理变量。"""
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _expand(value: str, plugin_id: str) -> str:
    """把 plugin.json 里的占位换成真实路径。"""
    subs = {
        "${state}": str(state_root()),
        "${plugin}": plugin_id,
        "${appdata}": os.environ.get("APPDATA", ""),
        "${localappdata}": os.environ.get("LOCALAPPDATA", ""),
        "${home}": str(Path.home()),
    }
    out = value
    for key, val in subs.items():
        out = out.replace(key, val)
    return out


def seed_cli_files(manifest: Manifest) -> list[str]:
    """把本机的 CLI 配置（登录凭证之类）复制进宿主的私有目录。

    宿主跑在受限上下文里，子进程写不了 %APPDATA%，而 bili 这类 CLI 需要一个
    可写的 home 才能记录状态。复制只在目标缺失或源更新时发生，且目标只能在
    state_root() 下面（manifest 校验已经卡住这一点）。
    """
    copied: list[str] = []
    for entry in manifest.cli_seed:
        src = Path(_expand(entry["from"], manifest.id))
        dst = Path(_expand(entry["to"], manifest.id))
        if not src.is_file():
            continue
        try:
            if dst.is_file() and dst.stat().st_mtime >= src.stat().st_mtime:
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            copied.append(dst.name)
        except OSError:
            continue
    return copied


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
                "extract": self._extract,
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
            if cap == "extract" and "browser" not in self.manifest.capabilities:
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
            self._inject_cookie(headers, req)

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

    def _inject_cookie(self, headers: dict[str, str], req: dict[str, Any] | None = None) -> None:
        """credential=self：用插件自己配置的 cookie（宿主读取，明文不出宿主）。

        cookieCase 是给那些「JSON 里存小写、HTTP 头必须大写」的平台用的：
        B 站凭证文件是 sessdata/dedeuserid，而 api.bilibili.com 只认
        SESSDATA/DedeUserID，键名原样拼会得到 code -101（账号未登录）。
        """
        req = req or {}
        raw = self.settings.get("cookie")
        if raw:
            headers["Cookie"] = str(raw)
            return
        cookie_file = self.settings.get("cookieFile")
        if not cookie_file:
            return
        path = Path(_expand(str(cookie_file), self.manifest.id))
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        case = str(req.get("cookieCase") or self.settings.get("cookieCase") or "keep").lower()
        def name_of(key: Any) -> str:
            key = str(key)
            if case == "upper":
                return key.upper()
            if case == "lower":
                return key.lower()
            return key
        if isinstance(data, dict) and isinstance(data.get("cookies"), list):
            pairs = [f"{name_of(c.get('name'))}={c.get('value')}" for c in data["cookies"] if c.get("name")]
            if pairs:
                headers["Cookie"] = "; ".join(pairs)
        elif isinstance(data, dict):
            headers["Cookie"] = "; ".join(f"{name_of(k)}={v}" for k, v in data.items())

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
        env = clean_env()
        state = str(state_root())
        for key, raw in self.manifest.cli_env.items():
            value = _expand(raw, self.manifest.id)
            env[key] = value
            if value.startswith(state):
                Path(value).mkdir(parents=True, exist_ok=True)
        seeded = seed_cli_files(self.manifest)
        if seeded:
            self.log("info", "cli 初始化 " + ",".join(seeded))
        proc = subprocess.run([resolved, *argv[1:]], capture_output=True, timeout=timeout,
                              env=env, cwd=str(Path.home()))
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
        # 详情与评论会被前端同时请求，两边都要开 Chrome 用同一个 user-data-dir，
        # 第二个进程会直接把第一个顶掉（TargetClosedError）。串行执行最稳。
        with BROWSER_LOCK:
            return self._browser_locked(req)

    def _browser_locked(self, req: dict[str, Any]) -> dict[str, Any]:
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

        cdp_mode = browser_cdp.enabled()
        profile = self.settings.get("browserProfile") or str(
            browser_profile(self.manifest.id))
        if not cdp_mode:
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
        guard = None
        pw = sync_playwright().start()
        ctx = None
        page = None
        try:
            if cdp_mode:
                browser_cdp.ensure()
                _browser, ctx = browser_cdp.connect(pw)
                page = ctx.new_page()
            else:
                guard = _ProfileGuard(profile)
                guard.acquire()
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

            # 评论弹层自己吞滚轮，滚之前得先把鼠标挪进弹层里，否则滚的是背后的页面。
            point = req.get("scrollPoint") or {}
            px = int(point.get("x") or 0)
            py = int(point.get("y") or 0)

            def _scroll(times: int, force: bool = False) -> None:
                for _ in range(times):
                    if not force and bodies and req.get("stopWhenMatched", True):
                        return
                    if time.time() > deadline:
                        return
                    if px and py:
                        page.mouse.move(px, py)
                    page.mouse.wheel(0, dy)
                    page.wait_for_timeout(interval)

            _scroll(scroll_times)

            # 有些平台的评论是点按钮才发请求的（知乎「N 条评论」），
            # 所以允许插件给几个选择器，滚完屏之后依次点一下。
            # 点开之后评论区才存在，得再滚一轮才会继续翻页。
            clicks = req.get("click") or []
            if isinstance(clicks, str):
                clicks = [clicks]
            clicked = False
            for selector in [str(s) for s in clicks][:4]:
                try:
                    node = page.query_selector(selector)
                    if node is None:
                        continue
                    node.click(timeout=3000)
                    clicked = True
                    page.wait_for_timeout(min(max(interval * 2, 1200), 4000))
                except Exception:
                    continue
            if clicked:
                _scroll(scroll_times, force=True)

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
                if cdp_mode and page is not None:
                    page.close()
            finally:
                try:
                    if not cdp_mode and ctx is not None:
                        ctx.close()
                finally:
                    pw.stop()
                    if guard is not None:
                        guard.release()

    # ------------------------------------------------------------ extract
    def _new_context(self, pw, profile: str, headless: bool):
        return pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            executable_path=_find_chrome(),
            headless=headless,
            locale="zh-CN",
            viewport={"width": 1440, "height": 900},
            user_agent=UA,
            args=["--disable-blink-features=AutomationControlled", "--window-size=1440,900"],
        )

    def _extract(self, req: dict[str, Any]) -> dict[str, Any]:
        with BROWSER_LOCK:
            return self._extract_locked(req)

    def _extract_locked(self, req: dict[str, Any]) -> dict[str, Any]:
        """按名字跑一个宿主内置的页内提取器（插件不能自带 JS）。

        为什么不在服务端解析 HTML：小红书把 undefined / new Map([]) 写进了
        __INITIAL_STATE__，知乎的内容在 js-initialData 里，都得让页面自己算。
        """
        from playwright.sync_api import sync_playwright

        name = str(req.get("name") or "")
        spec = EXTRACTORS.get(name)
        if spec is None:
            raise PermissionError("未知提取器：" + name + "（可用：" + ", ".join(EXTRACTORS) + "）")

        url = str(req.get("url") or "")
        if not url.startswith(("http://", "https://")):
            raise ValueError("extract 需要 http(s) url")
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        if not any(host == h or host.endswith("." + h) for h in spec["hosts"]):
            raise PermissionError("提取器 " + name + " 只认 " + "/".join(spec["hosts"]) + " 的页面")

        timeout_ms = min(int(req.get("timeoutMs") or 45000), 90000)
        settle_ms = min(int(req.get("settleMs") or spec.get("settleMs") or 3000), 15000)
        cdp_mode = browser_cdp.enabled()
        profile = self.settings.get("browserProfile") or str(browser_profile(self.manifest.id))
        if not cdp_mode:
            Path(profile).mkdir(parents=True, exist_ok=True)

        ensure_temp_env()
        self.log("info", "extract " + name + " " + url[:120])
        guard = None
        pw = sync_playwright().start()
        ctx = None
        page = None
        try:
            if cdp_mode:
                browser_cdp.ensure()
                _browser, ctx = browser_cdp.connect(pw)
                page = ctx.new_page()
            else:
                guard = _ProfileGuard(profile)
                guard.acquire()
                ctx = self._new_context(pw, profile, bool(req.get("headless", True)))
                self._inject_browser_cookies(ctx)
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_timeout(settle_ms)
            value = page.evaluate(spec["js"])
            return {"url": page.url, "name": name, "value": value}
        finally:
            try:
                if cdp_mode and page is not None:
                    page.close()
            finally:
                try:
                    if not cdp_mode and ctx is not None:
                        ctx.close()
                finally:
                    pw.stop()
                    if guard is not None:
                        guard.release()

    def _cookie_path(self) -> Path | None:
        """cookie 文件查找顺序：settings.cookieFile → 状态目录 cookies/<plugin_id>.json。

        后者是客户端登录成功后该写的地方（宿主与客户端约定，插件看不到内容）。
        """
        raw = self.settings.get("cookieFile")
        if raw:
            path = Path(_expand(str(raw), self.manifest.id))
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
