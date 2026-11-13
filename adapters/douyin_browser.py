"""抖音 adapter：真浏览器回放，监听 v2/module/feed 响应。

不接触签名。浏览器自己算 a_bogus + timestamp + x-secsdk-web-signature。
登录态来自 dy-cli 的 storage_state（~/.dy/cookies/default.json），或专用 profile 首跑扫码。
详见 ../DY_FEED_FINDINGS.md
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable

from .models import Comment, Item, clamp

FEED_RE = re.compile(r"/aweme/v2/web/module/feed/")
COMMENT_RE = re.compile(r"/aweme/v1/web/comment/list/")
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def _first_url(obj: Any) -> str:
    if isinstance(obj, dict):
        lst = obj.get("url_list") or []
        return lst[0] if lst else ""
    return ""


class DouyinBrowserAdapter:
    platform = "douyin"

    def __init__(
        self,
        profile_dir: str = os.path.expanduser("~/.onefeed/dy-profile"),
        headless: bool = False,
        cookie_file: str = os.path.expanduser("~/.dy/cookies/default.json"),
        settle_ms: int = 4000,
        log: Callable[[str], None] = print,
    ):
        self.profile_dir = profile_dir
        self.headless = headless
        self.cookie_file = cookie_file
        self.settle_ms = settle_ms
        self.log = log
        self._pw = None
        self._ctx = None
        self._page = None
        self._buffer: dict[str, Item] = {}
        self._fresh: list[str] = []
        self._logged_in = False

    # ---------------- lifecycle ----------------
    @staticmethod
    def find_chrome() -> str:
        for p in CHROME_CANDIDATES:
            if p and os.path.exists(p):
                return p
        raise FileNotFoundError("找不到 Chrome/Edge，装一个或传 executable_path")

    def start(self) -> None:
        from playwright.sync_api import sync_playwright

        os.makedirs(self.profile_dir, exist_ok=True)
        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            executable_path=self.find_chrome(),
            headless=self.headless,
            locale="zh-CN",
            viewport={"width": 1440, "height": 900},
            user_agent=UA,
            args=["--disable-blink-features=AutomationControlled", "--window-size=1440,900"],
        )
        cookies = self._load_cookies()
        if cookies:
            try:
                self._ctx.add_cookies(cookies)
                self.log(f"[douyin] 复用 {len(cookies)} 个 cookie（{self.cookie_file}）")
            except Exception as exc:
                self.log(f"[douyin] cookie 注入失败: {exc}")
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        self._page.on("response", self._on_response)
        self._page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=45_000)
        self._logged_in = self._detect_login()
        self.log(f"[douyin] 打开 {self._page.url[:60]} 登录态={self._logged_in}")
        if not self._await_feed():
            self.log("[douyin] 首屏没等到 feed 响应，pull 时会再试")

    def _await_feed(self, rounds: int = 6, step_ms: int = None) -> bool:
        """抖音首屏响应时快时慢（实测 3~15s），轮询 + 滚动 + 一次重载兜底。"""
        step = step_ms or self.settle_ms
        for r in range(rounds):
            if self._buffer:
                return True
            self._page.wait_for_timeout(step)
            try:
                self._page.mouse.wheel(0, 2400)
            except Exception:
                pass
            if r == 2 and not self._buffer:
                self.log("[douyin] 前 3 轮无响应，重载一次")
                try:
                    self._page.reload(wait_until="domcontentloaded", timeout=45_000)
                except Exception:
                    pass
        return bool(self._buffer)

    def _load_cookies(self) -> list[dict]:
        """兼容 dy-cli 的 storage_state 格式和纯 name=value dict。"""
        if not os.path.exists(self.cookie_file):
            return []
        try:
            with open(self.cookie_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        if isinstance(data, dict) and isinstance(data.get("cookies"), list):
            out = []
            for c in data["cookies"]:
                if not isinstance(c, dict) or not c.get("name"):
                    continue
                out.append({
                    "name": c["name"], "value": c.get("value", ""),
                    "domain": c.get("domain") or ".douyin.com",
                    "path": c.get("path") or "/",
                    "httpOnly": bool(c.get("httpOnly")),
                    "secure": bool(c.get("secure")),
                    "sameSite": c.get("sameSite") or "Lax",
                })
            return out
        if isinstance(data, dict):
            return [{"name": k, "value": str(v), "domain": ".douyin.com", "path": "/"}
                    for k, v in data.items()]
        return []

    def _detect_login(self) -> bool:
        try:
            return self._page.evaluate(
                "() => !!document.cookie.split('; ').find(c => c.startsWith('passport_csrf_token') || c.startsWith('sessionid'))"
            )
        except Exception:
            return False

    def close(self) -> None:
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    # ---------------- feed ----------------
    def _on_response(self, resp) -> None:
        if not FEED_RE.search(resp.url):
            return
        try:
            body = resp.json()
        except Exception:
            return
        for aweme in body.get("aweme_list") or []:
            item = self._normalize(aweme)
            if item and item.id not in self._buffer:
                self._buffer[item.id] = item
                self._fresh.append(item.id)

    def _normalize(self, aweme: dict) -> Item | None:
        aid = aweme.get("aweme_id")
        if not aid:
            return None
        video = aweme.get("video") or {}
        cover = _first_url(video.get("cover")) or _first_url(video.get("origin_cover")) \
            or _first_url(video.get("dynamic_cover"))
        dur = video.get("duration") or 0
        stat = aweme.get("statistics") or {}
        author = aweme.get("author") or {}
        tags = [t.get("hashtag_name") for t in (aweme.get("text_extra") or []) if t.get("hashtag_name")]
        return Item(
            id=f"douyin:{aid}",
            platform="douyin",
            raw_id=str(aid),
            title=(aweme.get("desc") or "").strip()[:200],
            author=author.get("nickname") or "",
            author_id=author.get("sec_uid") or "",
            cover=cover,
            url=f"https://www.douyin.com/video/{aid}",
            published_at=clamp(aweme.get("create_time")),
            duration=int(dur / 1000) if dur > 10_000 else int(dur),
            like=clamp(stat.get("digg_count")),
            comment=clamp(stat.get("comment_count") if stat.get("comment_count") is not None
                          else aweme.get("comment_count")),
            share=clamp(stat.get("share_count")),
            view=clamp(stat.get("play_count")),
            extra={"hashtags": tags, "collect": clamp(stat.get("collect_count")),
                   "is_top": bool(aweme.get("is_top")), "stat_keys": sorted(stat.keys()) if not stat.get("comment_count") else None},
        )

    def pull(self, limit: int = 20, scrolls: int = 4) -> list[Item]:
        """滚动取流。首屏通常已有 20 条；不够再滚，滚完返回新增的那批。"""
        self._fresh.clear()
        deadline = time.time() + 30
        for _ in range(scrolls):
            if len(self._fresh) >= limit:
                break
            self._page.mouse.wheel(0, 3000)
            self._page.wait_for_timeout(self.settle_ms)
            if time.time() > deadline:
                break
        if not self._buffer and not self._await_feed(rounds=3):
            raise RuntimeError("抖音 feed 响应超时：页面可能停在登录/验证页，headed 打开看一次")
        fresh = [self._buffer[i] for i in self._fresh if i in self._buffer]
        if not fresh:  # 冷启动：buffer 里已有旧数据时也要能返回
            fresh = list(self._buffer.values())
        fresh.sort(key=lambda x: x.published_at, reverse=True)
        self.log(f"[douyin] pull 拿到 {len(fresh)} 条（buffer {len(self._buffer)}）")
        return fresh[:limit]

    # ---------------- comments ----------------
    def comments(self, item: Item, limit: int = 20) -> list[Comment]:
        box: list[dict] = []
        page = self._ctx.new_page()

        def on_resp(resp):
            if not COMMENT_RE.search(resp.url):
                return
            try:
                box.append(resp.json())
            except Exception:
                pass

        page.on("response", on_resp)
        try:
            page.goto(f"https://www.douyin.com/video/{item.raw_id}",
                      wait_until="domcontentloaded", timeout=45_000)
            # 评论接口在 www-hj.douyin.com 子域，首屏 6~10s 才发，轮询等
            for _ in range(8):
                page.wait_for_timeout(2000)
                if sum(len(b.get("comments") or []) for b in box) >= 3:
                    break
        finally:
            page.close()
        out: list[Comment] = []
        for body in box:
            for c in body.get("comments") or []:
                cm = Comment(
                    id=f"douyin:{c.get('cid')}",
                    platform="douyin",
                    item_id=item.id,
                    author=((c.get("user") or {}).get("nickname") or ""),
                    text=(c.get("text") or "")[:500],
                    like=clamp(c.get("digg_count")),
                    reply_count=clamp(c.get("reply_comment_total")),
                    created_at=clamp(c.get("create_time")),
                )
                for rp in c.get("reply_comment") or []:
                    cm.replies.append(Comment(
                        id=f"douyin:{rp.get('cid')}",
                        platform="douyin", item_id=item.id,
                        author=((rp.get("user") or {}).get("nickname") or ""),
                        text=(rp.get("text") or "")[:500],
                        like=clamp(rp.get("digg_count")),
                        created_at=clamp(rp.get("create_time")),
                    ))
                out.append(cm)
            if len(out) >= limit:
                break
        return out[:limit]
