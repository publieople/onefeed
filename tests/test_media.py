"""T47 验收：媒体边车与 embed 兜底直链。

跑法：
    python tests/test_media.py
只管纯函数：slot 解析、embed 白名单、兜底直链透传。真取流在 e2e 里。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onefeed.media import (MediaBlocked, _SafeRedirect, _ensure_public_http,  # noqa: E402
                           fetch_image, resolve_slot)
from plugin_runtime.host import PluginHost  # noqa: E402

VERBOSE = "--verbose" in sys.argv
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


def normalize(media: dict, embeds=("douyin",), plugin_id="douyin") -> dict | None:
    manifest = SimpleNamespace(id=plugin_id, embeds=list(embeds), features=["detail"])
    return PluginHost(plugins_dir=Path("."))._normalize_media(manifest, media)


def test_video_slot() -> None:
    file_media = {"type": "file", "url": "https://cdn.example/a.mp4", "referer": "https://x.example/"}
    check(resolve_slot({"media": file_media}, "video") ==
          {"url": "https://cdn.example/a.mp4", "referer": "https://x.example/"}, "file 型直接给 url 与 referer")

    embed = {"type": "embed", "embedUrl": "https://open.douyin.com/player/video?vid=1",
             "fallbackUrl": "https://v26-web.douyinvod.com/x.mp4", "fallbackReferer": "https://www.douyin.com/"}
    check(resolve_slot({"media": embed}, "video") ==
          {"url": "https://v26-web.douyinvod.com/x.mp4", "referer": "https://www.douyin.com/"},
          "embed 型优先回兜底直链")

    check(resolve_slot({"media": {"type": "embed", "embedUrl": "https://open.douyin.com/player/video?vid=1"}}, "video") is None,
          "没有兜底直链的 embed 取不到 video 位")
    check(resolve_slot({}, "video") is None, "没有 media 时取不到 video 位")


def test_other_slots() -> None:
    detail = {"media": {"type": "file", "url": "https://a/b.mp4", "poster": "https://a/p.jpg"},
              "images": ["https://a/0.jpg", "https://a/1.jpg"]}
    check(resolve_slot(detail, "poster") == {"url": "https://a/p.jpg", "referer": ""}, "poster 取 media.poster")
    check(resolve_slot(detail, "img-1") == {"url": "https://a/1.jpg", "referer": ""}, "img-N 取第 N 张图")
    check(resolve_slot(detail, "img-9") is None, "越界的 img-N 取不到")
    check(resolve_slot({"media": {}}, "poster") is None, "缺 poster 时取不到")


def test_normalize_keeps_fallback() -> None:
    media = normalize({"type": "embed", "embedUrl": "https://open.douyin.com/player/video?vid=1",
                       "poster": "https://p3.douyinpic.com/c.jpg", "fallbackUrl": "https://v26-web.douyinvod.com/x.mp4",
                       "fallbackReferer": "https://www.douyin.com/"})
    check(media is not None and media["type"] == "embed", "官方播放器在白名单里时保留 embed")
    check(media.get("fallbackUrl") == "https://v26-web.douyinvod.com/x.mp4", "兜底直链透传给前端")
    check(media.get("fallbackReferer") == "https://www.douyin.com/", "兜底直链的 Referer 一起带上")

    dropped = normalize({"type": "embed", "embedUrl": "https://evil.example/player", "fallbackUrl": "https://x/a.mp4"})
    check(dropped is None, "未声明的嵌入源整条丢弃（兜底也跟着没了）")

    no_fallback = normalize({"type": "embed", "embedUrl": "https://open.douyin.com/player/video?vid=1"})
    check("fallbackUrl" not in (no_fallback or {}), "没有兜底时不留空字段")


def test_normalize_detail() -> None:
    manifest = SimpleNamespace(id="douyin", embeds=["douyin"], features=["detail"])
    out = PluginHost(plugins_dir=Path("."))._normalize_detail(manifest, {
        "body": {"kind": "text", "value": "正文"},
        "media": {"type": "embed", "embedUrl": "https://open.douyin.com/player/video?vid=1",
                  "fallbackUrl": "https://v26-web.douyinvod.com/x.mp4"},
        "note": "备注",
        "unknown": "不该出现",
    })
    check(out["media"]["fallbackUrl"] == "https://v26-web.douyinvod.com/x.mp4", "详情白名单里保留兜底直链")
    check("unknown" not in out, "白名单外字段被丢掉")


def test_media_blocks_private_targets() -> None:
    """媒体边车只取公网 http(s)：内网/环回/文件协议和跨跳转都要拦住。"""
    import urllib.request

    blocked = [
        "http://127.0.0.1:8765/api/health",
        "http://localhost/secret",
        "http://10.0.0.1/secret",
        "http://192.168.1.1/secret",
        "http://169.254.169.254/latest/meta-data",
        "http://224.0.0.1/secret",
        "http://[::1]/secret",
        "file:///etc/passwd",
        "ftp://example.com/x",
    ]
    for url in blocked:
        try:
            _ensure_public_http(url)
        except MediaBlocked:
            pass
        else:
            raise AssertionError(f"应当拦住：{url}")

    _ensure_public_http("https://1.1.1.1/x")   # 公网 IP 字面量，不依赖 DNS/网络

    # 图取自不可信输入：撞到内网地址时返回 None，不让总结整个失败
    check(fetch_image("http://127.0.0.1/secret.jpg") is None,
          "fetch_image 对拦截地址返回 None")

    # 302 跳到内网同样要拦，不能只校验第一跳
    req = urllib.request.Request("https://1.1.1.1/a")
    try:
        _SafeRedirect().redirect_request(req, None, 302, "Found", {},
                                         "http://127.0.0.1/secret")
    except MediaBlocked:
        pass
    else:
        raise AssertionError("跨跳转到 127.0.0.1 没有被拦住")


def test_media_route_blocks_private_url() -> None:
    """整条路由的映射：拦下来的地址回 400 media_blocked，不是 502。"""
    import os
    import tempfile
    import time

    from fastapi.testclient import TestClient

    from onefeed.app import create_app
    from onefeed.store import Store

    state = tempfile.mkdtemp(prefix="onefeed-media-ssrf-")
    old_home = os.environ.get("ONEFEED_HOME")
    os.environ["ONEFEED_HOME"] = state
    store = None
    try:
        store = Store(Path(state) / "media-ssrf.db")
        now = int(time.time())
        store.upsert_items([{
            "id": "xiaohongshu:blocked:1", "platform": "xiaohongshu", "kind": "video",
            "title": "指向内网的媒体", "text": "", "author": "作者", "cover": "",
            "url": "https://www.xiaohongshu.com/explore/1", "published_at": now,
            "like": 0, "comment": 0, "share": 0, "view": 0,
            "tags": [], "extra": {}, "fetched_at": now,
        }])
        store.save_detail("xiaohongshu:blocked:1", {
            "media": {"type": "file", "url": "http://127.0.0.1:8765/api/health",
                      "referer": "https://www.xiaohongshu.com/"},
        })

        client = TestClient(create_app(store))
        resp = client.get("/api/media/xiaohongshu%3Ablocked%3A1/video")
        check(resp.status_code == 400, "指向内网的媒体回 400")
        check(resp.json()["error"]["code"] == "media_blocked", "错误码是 media_blocked")
    finally:
        if store is not None:
            store.close()
        if old_home is None:
            os.environ.pop("ONEFEED_HOME", None)
        else:
            os.environ["ONEFEED_HOME"] = old_home


def test_route_refreshes_expired_link() -> None:
    """T46：直链过期（403）时重取一次详情、写回缓存、用新地址再取一次流。"""
    import os
    import tempfile
    import time

    from fastapi.testclient import TestClient

    from onefeed import api as api_mod
    from onefeed.app import create_app
    from onefeed.store import Store

    state = tempfile.mkdtemp(prefix="onefeed-media-")
    old_home = os.environ.get("ONEFEED_HOME")
    os.environ["ONEFEED_HOME"] = state
    store = None
    try:
        store = Store(Path(state) / "media-test.db")
        now = int(time.time())
        store.upsert_items([{
            "id": "douyin:video:1", "platform": "douyin", "kind": "video",
            "title": "一条用于直链过期的视频", "text": "", "author": "作者", "cover": "",
            "url": "https://www.douyin.com/video/1", "published_at": now,
            "like": 0, "comment": 0, "share": 0, "view": 0,
            "tags": [], "extra": {}, "fetched_at": now,
        }])
        store.save_detail("douyin:video:1", {
            "body": {"kind": "text", "value": "旧详情"},
            "media": {"type": "file", "url": "https://cdn.example/old.mp4",
                      "referer": "https://www.douyin.com/"},
        })

        class FakeHost:
            def __init__(self) -> None:
                self.detail_calls = 0

            def supports(self, plugin_id: str, feature: str) -> bool:
                return feature == "detail"

            def get(self, plugin_id: str):
                return SimpleNamespace(id=plugin_id, media_hosts=["*.example"],
                                       embeds=[], features=["detail"])

            def detail(self, plugin_id: str, item) -> dict:
                self.detail_calls += 1
                return {"body": {"kind": "text", "value": "新详情"},
                        "media": {"type": "file", "url": "https://cdn.example/new.mp4",
                                  "referer": "https://www.douyin.com/"}}

        class FakeResp:
            def __init__(self, payload: bytes = b"") -> None:
                self.payload = payload
                self.closed = False

            def read(self, n: int = -1) -> bytes:
                data, self.payload = self.payload, b""
                return data

            def close(self) -> None:
                self.closed = True

        host = FakeHost()
        app = create_app(store)
        app.state.refresher.host = host
        api_mod._MEDIA_REFRESH_AT.clear()
        calls: list[str] = []

        def fake_open(url: str, referer: str = "", cookie: str = "",
                      range_header: str | None = None):
            calls.append(url)
            if url.endswith("old.mp4"):
                return 403, {}, FakeResp()
            return 200, {"content-type": "video/mp4", "content-length": "3"}, FakeResp(b"abc")

        orig = api_mod.media_mod.open_stream
        api_mod.media_mod.open_stream = fake_open
        try:
            client = TestClient(app)
            good = client.get("/api/media/douyin%3Avideo%3A1/video")
            check(good.status_code == 200, "旧直链 403 时自动重取详情，最终 200")
            check(good.content == b"abc", "返回的是新地址的字节")
            check(calls == ["https://cdn.example/old.mp4", "https://cdn.example/new.mp4"],
                  "先试旧地址、再试新地址，各一次")
            check(host.detail_calls == 1, "只重取一次详情")
            cached = store.get_detail("douyin:video:1", max_age=0)
            check(cached["payload"]["media"]["url"] == "https://cdn.example/new.mp4",
                  "新详情写回 details 表")

            # 新地址也过期：只重试一次就放弃，别死循环
            calls.clear()

            def always_403(url: str, referer: str = "", cookie: str = "",
                           range_header: str | None = None):
                calls.append(url)
                return 403, {}, FakeResp()

            api_mod.media_mod.open_stream = always_403
            api_mod._MEDIA_REFRESH_AT.clear()
            bad = client.get("/api/media/douyin%3Avideo%3A1/video")
            check(bad.status_code == 502, "两轮都过期就报 502")
            check(bad.json()["error"]["code"] == "media_expired", "错误码是 media_expired")
            check(len(calls) == 2, "最多两轮请求，不无限重试")
            check(host.detail_calls == 2, "第二次过期也只会再重取一次详情")

            # 冷却期：同一条内容 60 秒内不再重取详情，直接按过期报错
            api_mod._MEDIA_REFRESH_AT.clear()
            api_mod.media_mod.open_stream = fake_open
            calls.clear()
            host.detail_calls = 0
            store.save_detail("douyin:video:1", {
                "media": {"type": "file", "url": "https://cdn.example/old.mp4",
                          "referer": "https://www.douyin.com/"}})
            first = client.get("/api/media/douyin%3Avideo%3A1/video")
            check(first.status_code == 200 and host.detail_calls == 1, "第一次仍会重取")
            store.save_detail("douyin:video:1", {
                "media": {"type": "file", "url": "https://cdn.example/old.mp4",
                          "referer": "https://www.douyin.com/"}})
            second = client.get("/api/media/douyin%3Avideo%3A1/video")
            check(second.status_code == 502 and host.detail_calls == 1,
                  "冷却期内不再重取详情，直接报过期")
        finally:
            api_mod.media_mod.open_stream = orig
    finally:
        if store is not None:
            store.close()
        if old_home is None:
            os.environ.pop("ONEFEED_HOME", None)
        else:
            os.environ["ONEFEED_HOME"] = old_home


def main() -> int:
    test_video_slot()
    test_other_slots()
    test_normalize_keeps_fallback()
    test_normalize_detail()
    test_media_blocks_private_targets()
    test_media_route_blocks_private_url()
    test_route_refreshes_expired_link()
    print(f"✅ test_media.py  T47 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
