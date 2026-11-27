"""OF-03 验收：媒体边车只代取公网内容，非图片字节不进缓存。

跑法：
    python tests/test_media_guard.py

不联网：DNS 用假 getaddrinfo，opener 用假 response，接口层用 TestClient 打真实路由。
"""
from __future__ import annotations

import atexit
import hashlib
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TMP_STATE = Path(tempfile.mkdtemp(prefix="of-media-guard-"))
os.environ["ONEFEED_HOME"] = str(_TMP_STATE)


def _drop_tmp_state() -> None:
    import gc

    gc.collect()
    for _ in range(4):
        shutil.rmtree(_TMP_STATE, ignore_errors=True)
        if not _TMP_STATE.exists():
            return
        time.sleep(0.15)


atexit.register(_drop_tmp_state)

from fastapi.testclient import TestClient  # noqa: E402

from onefeed import api as api_mod  # noqa: E402
from onefeed import media  # noqa: E402
from onefeed.app import create_app  # noqa: E402
from onefeed.store import Store  # noqa: E402

VERBOSE = "--verbose" in sys.argv
CHECKS = 0
PUBLIC_DNS = [("", "", "", "", ("93.184.216.34", 0))]
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


def expect_permission(fn, label: str) -> str:
    global CHECKS
    try:
        fn()
    except PermissionError as exc:
        CHECKS += 1
        if VERBOSE:
            print(f"  ok  {label}")
        return str(exc)
    raise AssertionError(label + "（没有抛 PermissionError）")


class FakeResp:
    def __init__(self, payload: bytes = b"", status: int = 200, headers=None) -> None:
        self.payload = payload
        self.status = status
        self.headers = dict(headers or {})
        self.closed = False

    def read(self, n: int = -1) -> bytes:
        data, self.payload = self.payload, b""
        return data

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------- 类型嗅探
def case_sniff() -> None:
    check(media._sniff_mime(b"\xff\xd8\xff\xe0" + b"\x00" * 8) == "image/jpeg", "JPEG 头")
    check(media._sniff_mime(PNG) == "image/png", "PNG 头")
    check(media._sniff_mime(b"GIF89a" + b"\x00" * 6) == "image/gif", "GIF 头")
    check(media._sniff_mime(b"RIFF\x00\x00\x00\x00WEBP") == "image/webp", "WEBP 头")
    check(media._sniff_mime(b'{"marker":"INTERNAL-ENDPOINT-REACHED"}') == "",
          "JSON 认不出来（以前兜底成 image/jpeg）")
    check(media._sniff_mime(b"<!doctype html><html>") == "", "HTML 认不出来")


# ---------------------------------------------------------------- 图片缓存
def case_fetch_image_only_images() -> None:
    orig = media.open_stream
    try:
        json_key = "of03-json-not-image"
        json_resp = FakeResp(b'{"marker":"INTERNAL-ENDPOINT-REACHED","db":"C:/Users/a/onefeed.db"}',
                             headers={"content-type": "application/json"})
        media.open_stream = lambda *a, **k: (200, json_resp.headers, json_resp)
        got = media.fetch_image("https://cdn.example/api/settings", cache_key=json_key)
        check(got is None, "JSON 响应不当图片返回")
        check(media._read_cached_image(json_key) is None, "JSON 没有被写进图片缓存")

        png_key = "of03-png-image"
        media.open_stream = lambda *a, **k: (200, {}, FakeResp(PNG))
        got = media.fetch_image("https://cdn.example/p.png", cache_key=png_key)
        check(got is not None and got[1] == "image/png", "真图片按 PNG 返回")
        cached = media._read_cached_image(png_key)
        check(cached is not None and cached[0] == PNG, "真图片进了缓存且能读回")
    finally:
        media.open_stream = orig

    # 旧版本（sniff 兜底 image/jpeg）留下的非图片缓存：读的时候作废并删掉
    legacy_key = "of03-legacy-json"
    legacy = media._image_cache_dir() / (hashlib.sha1(legacy_key.encode()).hexdigest() + ".bin")
    legacy.write_bytes(b'{"legacy":"not-an-image"}')
    check(media._read_cached_image(legacy_key) is None, "旧版留下的非图片缓存不被当图片")
    check(not legacy.exists(), "作废的缓存文件被删掉")


# ---------------------------------------------------------------- 出站边界
def case_open_stream_blocks() -> None:
    for url in ("http://127.0.0.1:8791/api/settings",
                "http://localhost:8791/api/settings",
                "http://192.168.1.10/x",
                "http://169.254.169.254/latest/meta-data/",
                "file:///C:/Windows/win.ini"):
        expect_permission(lambda u=url: media.open_stream(u), f"拒绝代取 {url}")

    # 公网地址照常发起请求：guard 不能误伤正常媒体。opener 用假的，防止真联网。
    fake = FakeResp(b"ok", headers={"content-type": "image/png"})
    with mock.patch.object(media.capabilities.socket, "getaddrinfo", return_value=PUBLIC_DNS), \
            mock.patch.object(media.urllib.request, "build_opener") as build:
        build.return_value.open.return_value = fake
        status, headers, resp = media.open_stream("https://cdn.example/cover.png")
        check(status == 200 and resp is fake, "公网地址照常发起请求")
        check(headers.get("content-type") == "image/png", "响应头原样带回")
        check(build.called, "用的是带重定向守卫的 opener")


def case_redirect_guard() -> None:
    handler = media._SafeRedirect()
    req = urllib.request.Request("https://cdn.example/a.mp4",
                                 headers={"Cookie": "sid=1", "Referer": "https://www.example/"})
    text = expect_permission(
        lambda: handler.redirect_request(req, None, 302, "Found", {},
                                         "http://127.0.0.1:8791/api/settings"),
        "302 跳到本机被拦")
    check("127.0.0.1" in text, "拦截信息里带目标地址")

    with mock.patch.object(media.capabilities.socket, "getaddrinfo", return_value=PUBLIC_DNS):
        new = handler.redirect_request(req, None, 302, "Found", {}, "https://img.example/b.jpg")
        check(new is not None and new.full_url == "https://img.example/b.jpg", "公网跨域重定向放行")
        check(new.get_header("Cookie") is None, "跨域重定向丢掉 Cookie")
        check(new.get_header("Referer") is None, "跨域重定向丢掉 Referer")
        same = handler.redirect_request(req, None, 302, "Found", {}, "https://cdn.example/b.jpg")
        check(same is not None and same.get_header("Cookie") == "sid=1", "同域重定向保留 Cookie")


# ---------------------------------------------------------------- 接口层（probe3 的形态）
def case_api_blocks_internal() -> None:
    store = Store(_TMP_STATE / "media-guard.db")
    try:
        now = int(time.time())
        store.upsert_items([{
            "id": "douyin:video:1", "platform": "douyin", "kind": "video",
            "title": "媒体地址指向宿主自己", "text": "", "author": "作者", "cover": "",
            "url": "https://www.douyin.com/video/1", "published_at": now,
            "like": 0, "comment": 0, "share": 0, "view": 0,
            "tags": [], "extra": {}, "fetched_at": now,
        }])
        store.save_detail("douyin:video:1", {
            "media": {"type": "file", "url": "http://127.0.0.1:8791/api/settings",
                      "referer": ""}})

        class FakeHost:
            def get(self, plugin_id: str):
                return SimpleNamespace(id=plugin_id, media_hosts=[], embeds=[],
                                       features=["detail"])

        app = create_app(store)
        app.state.refresher.host = FakeHost()
        api_mod._MEDIA_REFRESH_AT.clear()
        client = TestClient(app)

        resp = client.get("/api/media/douyin%3Avideo%3A1/video")
        check(resp.status_code == 400, f"内网视频地址返回 400（实际 {resp.status_code}）")
        body = resp.json()
        detail = body.get("error") or body.get("detail") or {}
        check(detail.get("code") == "media_blocked", f"错误码是 media_blocked（实际 {detail.get('code')}）")
        check("127.0.0.1" in str(detail.get("message")), "错误信息带被拒的地址")

        store.save_detail("douyin:video:1", {
            "media": {}, "images": ["http://127.0.0.1:8791/api/settings"]})
        resp = client.get("/api/media/douyin%3Avideo%3A1/img-0")
        check(resp.status_code == 400, f"内网图片地址返回 400（实际 {resp.status_code}）")
        body = resp.json()
        detail = body.get("error") or body.get("detail") or {}
        check(detail.get("code") == "media_blocked", "图片位的错误码也是 media_blocked")
    finally:
        store.close()


def main() -> int:
    case_sniff()
    case_fetch_image_only_images()
    case_open_stream_blocks()
    case_redirect_guard()
    case_api_blocks_internal()
    print(f"✅ test_media_guard.py  OF-03 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
