"""媒体边车（005 T34）：把「浏览器给不了的头」补上。

为什么需要中转：抖音的 play_addr 直链校验 Referer，<video src> 拿不到这个头；
小红书 xhscdn 不需要。所以这里只是**可选兜底**，不是所有平台都走。

边界（写在代码里，别靠自觉）：
- 地址只从 details 表里取，前端传的只能是 slot 名，传不了 URL
- Cookie 只注入 mediaHosts 白名单命中的域，跨域重定向一律丢
- 不落盘、不改内容，只透传 Range 与状态码
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
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


class MediaBlocked(ValueError):
    """媒体地址不让服务端取：不是公网 http(s)，或跳到了内网。"""


def _ensure_public_http(url: str) -> None:
    """只在发起请求前放行公网 http(s)。

    详情和插件给的是不可信输入：如果这里不拦，一个 http://127.0.0.1:8765
    就能让宿主替它扫内网（SSRF）。每一次重定向也要重新过一遍——302 到
    127.0.0.1 是同一类绕过。
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError as exc:
        raise MediaBlocked("媒体地址不合法") from exc
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise MediaBlocked("媒体地址不是 http(s)")
    if parsed.username or parsed.password:
        raise MediaBlocked("媒体地址不能带账号密码")

    host = parsed.hostname.strip().lower()
    if host == "localhost" or host.endswith(".local") or host.endswith(".localhost"):
        raise MediaBlocked("媒体地址指向本机")
    try:
        port = parsed.port
    except ValueError as exc:
        raise MediaBlocked("媒体地址端口不合法") from exc
    if port == 0:
        raise MediaBlocked("媒体地址端口不合法")

    try:
        infos = socket.getaddrinfo(
            host, port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM)
    except OSError as exc:
        raise MediaBlocked("媒体域名解析失败") from exc
    if not infos:
        raise MediaBlocked("媒体域名没有可用地址")

    for info in infos:
        addr = str(info[4][0]).split("%", 1)[0]   # 去掉 IPv6 的 scope id
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError as exc:
            raise MediaBlocked("媒体域名解析出了非法地址") from exc
        # is_global 覆盖私网、环回、链路本地、保留和未指定地址；组播要单独判，
        # 旧版 Python 的 is_global 对 224.0.0.0/4 仍会返回 True。
        if not ip.is_global or ip.is_multicast:
            raise MediaBlocked("媒体地址解析到非公网 IP")


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


IMAGE_CACHE_TTL = 6 * 3600      # 图片字节缓存 6 小时：签名直链会过期，重取一次比整条总结失败划算
IMAGE_MAX_BYTES = 8 * 1024 * 1024


def _image_cache_dir() -> Path:
    target = state_root() / "image-cache"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _read_cached_image(key: str) -> tuple[bytes, str] | None:
    import hashlib
    import time

    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    path = _image_cache_dir() / (digest + ".bin")
    try:
        if not path.is_file():
            return None
        if time.time() - path.stat().st_mtime > IMAGE_CACHE_TTL:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if not raw:
        return None
    return raw, _sniff_mime(raw)


def _write_cached_image(key: str, raw: bytes) -> None:
    import hashlib

    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
    try:
        (_image_cache_dir() / (digest + ".bin")).write_bytes(raw)
    except OSError:
        pass


def _sniff_mime(raw: bytes) -> str:
    """按文件头判断类型：CDN 返回的 Content-Type 经常是 application/octet-stream。"""
    head = raw[:12]
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"GIF8"):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def fetch_image(url: str, referer: str = "", plugin_id: str = "",
                cache_key: str = "") -> tuple[bytes, str] | None:
    """取一张图并缓存字节。失败返回 None——少一张图不该让整条总结失败。"""
    key = cache_key or url
    cached = _read_cached_image(key)
    if cached:
        return cached
    cookie = cookie_header(plugin_id) if plugin_id else ""
    for attempt in range(2):
        try:
            status, _headers, resp = open_stream(url, referer=referer, cookie=cookie)
        except MediaBlocked:
            return None   # 图取自不可信输入：拦住内网地址，别让整条总结因此失败
        try:
            raw = resp.read(IMAGE_MAX_BYTES)
        except Exception:  # noqa: BLE001 - 网络抖动按失败处理
            raw = b""
        finally:
            try:
                resp.close()
            except Exception:
                pass
        if status < 400 and raw:
            mime = _sniff_mime(raw)
            if mime.startswith("image/"):
                _write_cached_image(key, raw)
                return raw, mime
        # 第一次失败多半是签名过期；调用方会先把 detail 刷新一遍再传新 URL，这里只重试一次
        if attempt == 0:
            continue
        break
    return None


def read_slot_image(item_id: str, slot: str, detail: dict[str, Any],
                    plugin_id: str) -> tuple[bytes, str] | None:
    """按 slot 取图：img-N 走详情里的 images，poster 走 media.poster。"""
    target = resolve_slot(detail, slot)
    if not target:
        return None
    return fetch_image(target["url"], referer=target.get("referer", ""),
                       plugin_id=plugin_id, cache_key=item_id + ":" + slot)


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
    """跨域跳转时把 Cookie / Referer 丢掉，别把登录态送到 CDN 之外的域。

    跳转目标同样过 _ensure_public_http：公网 302 到 127.0.0.1 是 SSRF 的
    标准绕过，只校验初始 URL 不够。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        target = urllib.parse.urljoin(req.full_url, newurl or "")
        _ensure_public_http(target)
        new = super().redirect_request(req, fp, code, msg, headers, target)
        if new is None:
            return None
        old_host = (urllib.parse.urlparse(req.full_url).hostname or "").lower()
        new_host = (urllib.parse.urlparse(target).hostname or "").lower()
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
    _ensure_public_http(url)
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
