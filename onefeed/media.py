"""媒体边车（005 T34）：把「浏览器给不了的头」补上。

为什么需要中转：抖音的 play_addr 直链校验 Referer，<video src> 拿不到这个头；
小红书 xhscdn 不需要。所以这里只是**可选兜底**，不是所有平台都走。

边界（写在代码里，别靠自觉）：
- 地址只从 details 表里取，前端传的只能是 slot 名，传不了 URL
- Cookie 只注入 mediaHosts 白名单命中的域，跨域重定向一律丢
- 不落盘、不改内容，只透传 Range 与状态码
"""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from plugin_runtime.capabilities import UA
from plugin_runtime.paths import state_root

SLOT_RE = re.compile(r"^(video|poster|img-\d{1,2})$")
IMG_SLOT_RE = re.compile(r"^img-(\d{1,2})$")
CHUNK = 64 * 1024
MAX_BYTES = 240 * 1024 * 1024
SEMAPHORE = threading.BoundedSemaphore(4)   # 并发上限：一台机器刷六路，别把上行打满
# 图片和视频分开排队：一条 240MB 的视频占着名额时，一屏 30 张封面不该跟着干等。
IMAGE_SEMAPHORE = threading.BoundedSemaphore(8)


def semaphore_for(slot: str):
    """按媒体位挑队列：封面/正文图走图片队列，视频走视频队列。"""
    return IMAGE_SEMAPHORE if IMG_SLOT_RE.match(slot) else SEMAPHORE


def resolve_slot(detail: dict[str, Any], slot: str) -> dict[str, str] | None:
    """slot → {url, referer}。取不到就是 None，由调用方回 404。"""
    media = detail.get("media") if isinstance(detail, dict) else None
    media = media if isinstance(media, dict) else {}

    if slot == "video":
        kind = str(media.get("type") or "")
        if kind == "file":
            url = str(media.get("url") or "")
            referer = str(media.get("referer") or "")
        else:
            # 官方播放器（embed）的兜底直链：前端点「换直链」时才走这里
            url = str(media.get("fallbackUrl") or "")
            referer = str(media.get("fallbackReferer") or "")
        if not url:
            return None
        return {"url": url, "referer": referer}

    if slot == "poster":
        url = str(media.get("poster") or "")
        return {"url": url, "referer": str(media.get("referer") or "")} if url else None

    match = IMG_SLOT_RE.match(slot)
    if match:
        images = detail.get("images") or []
        index = int(match.group(1))
        if isinstance(images, list) and 0 <= index < len(images):
            return {"url": str(images[index]), "referer": ""}
    return None


def _host_allowed(host: str, patterns: list[str]) -> bool:
    host = (host or "").lower()
    for pattern in patterns or []:
        p = pattern.lower()
        if p.startswith("*."):
            suffix = p[1:]          # ".xhscdn.com"
            if host.endswith(suffix):
                return True
        elif host == p:
            return True
    return False


def cookie_header(plugin_id: str) -> str:
    """读宿主持有的 cookie（插件自己永远看不到），拼成 Cookie 头。"""
    path = state_root() / "cookies" / (plugin_id + ".json")
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    raw = data.get("cookies") if isinstance(data, dict) else None
    pairs: list[str] = []
    if isinstance(raw, list):
        pairs = [str(c.get("name")) + "=" + str(c.get("value", ""))
                 for c in raw if isinstance(c, dict) and c.get("name")]
    elif isinstance(raw, dict):
        pairs = [str(k) + "=" + str(v) for k, v in raw.items()]
    return "; ".join(pairs)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """跨域跳转时把 Cookie / Referer 丢掉，别把登录态送到 CDN 之外的域。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is None:
            return None
        old_host = (urllib.parse.urlparse(req.full_url).hostname or "").lower()
        new_host = (urllib.parse.urlparse(newurl).hostname or "").lower()
        if old_host != new_host:
            for key in ("Cookie", "Referer"):
                try:
                    new.remove_header(key)
                except Exception:
                    pass
        return new


def open_stream(url: str, referer: str = "", cookie: str = "",
                range_header: str | None = None) -> tuple[int, dict[str, str], Any]:
    """发起一次媒体请求，返回 (status, headers, response)。调用方负责 close。"""
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie
    if range_header:
        headers["Range"] = range_header

    opener = urllib.request.build_opener(_SafeRedirect)
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        resp = opener.open(request, timeout=30)
        return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc


def iter_body(resp: Any) -> Iterator[bytes]:
    """按块吐字节；总量超过 MAX_BYTES 就掐断（别让一个 4K 原片把内存吃光）。"""
    try:
        sent = 0
        while True:
            chunk = resp.read(CHUNK)
            if not chunk:
                break
            sent += len(chunk)
            if sent > MAX_BYTES:
                break
            yield chunk
    finally:
        try:
            resp.close()
        except Exception:
            pass
