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

from onefeed.media import resolve_slot  # noqa: E402
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


def main() -> int:
    test_video_slot()
    test_other_slots()
    test_normalize_keeps_fallback()
    test_normalize_detail()
    print(f"✅ test_media.py  T47 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
