"""三档总结粒度 + 条目对话的回归。

以前这些点只靠人手点：档位换了还是旧内容、换档把面板清空塌一下、
图文条目问「图里写了什么」答「看不到」、对话历史把整段塞回去。
这里钉住四件事：
1. 三档的差异是数字（条数/字数/素材长度/图张数），且单调；
2. 缓存与接口按 (条目, 档位) 分开，换档不会读到另一档的稿子；
3. 换档失败要退回上一份，而不是给一个空面板；
4. 对话带图、history 截断、问题在最后一条。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from onefeed import ai as ai_mod  # noqa: E402
from onefeed import settings as settings_mod  # noqa: E402
from onefeed import summary as summary_mod  # noqa: E402
from onefeed.app import create_app  # noqa: E402
from onefeed.store import Store  # noqa: E402

VERBOSE = "--verbose" in sys.argv
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


class _Patched:
    def __init__(self, fn):
        self.fn = fn
        self.before = None

    def __enter__(self):
        self.before = ai_mod.complete
        ai_mod.complete = self.fn
        return self

    def __exit__(self, *exc):
        ai_mod.complete = self.before
        return False


class _PatchedStream:
    def __init__(self, fn):
        self.fn = fn
        self.before = None

    def __enter__(self):
        self.before = ai_mod.stream_complete
        ai_mod.stream_complete = self.fn
        return self

    def __exit__(self, *exc):
        ai_mod.stream_complete = self.before
        return False


def timed(*pairs) -> dict:
    return {"basis": "transcript", "title": "标题", "duration": 600,
            "transcript": {"lines": [{"t": t, "text": text} for t, text in pairs]}}


def test_depths_are_ordered() -> None:
    """三档必须真的不一样，而且是单调的：越详细，条数/字数/素材越长。"""
    brief = summary_mod.depth_spec("brief")
    balanced = summary_mod.depth_spec("balanced")
    detailed = summary_mod.depth_spec("detailed")
    check(brief["points"][1] < balanced["points"][1] < detailed["points"][1],
          "上限条数逐档变大")
    check(brief["tldr"] < balanced["tldr"] < detailed["tldr"], "一句话字数逐档变长")
    check(brief["point"] < balanced["point"] < detailed["point"], "要点字数逐档变长")
    check(brief["tokens"] < balanced["tokens"] < detailed["tokens"], "输出预算逐档变大")
    check(brief["material"] < balanced["material"] < detailed["material"], "素材长度逐档变大")
    check(summary_mod.depth_spec("nope") is balanced, "不认识的档位回落平衡档")
    check(summary_mod.DEPTH_DEFAULT == "balanced", "默认档位是平衡")


def test_prompt_follows_depth() -> None:
    brief = summary_mod.system_prompt("brief")
    detailed = summary_mod.system_prompt("detailed")
    check("points 2 到 3 条" in brief, "简洁档提示词只要 2-3 条")
    check("points 6 到 10 条" in detailed, "详细档提示词要 6-10 条")
    check("24 字内" in brief and "60 字内" in detailed, "一句话长度按档位写进提示词")
    check(summary_mod.system_prompt("brief") != summary_mod.system_prompt("balanced"),
          "不同档位给出不同提示词")
    stream_brief = summary_mod.stream_prompt("brief")
    check("要点 2 到 3 条" in stream_brief, "流式提示词也按档位")
    check("TLDR:" in stream_brief and "- [mm:ss]" in stream_brief, "流式仍是行协议")


def test_detailed_keeps_more_points() -> None:
    """_parse 以前硬截 6 条：详细档的第 7-10 条会被吃掉。"""
    import json as jsonlib

    raw = jsonlib.dumps({"tldr": "x", "points": [{"t": None, "text": f"p{i}"} for i in range(9)]})
    check(len(summary_mod._parse(raw, 100)["points"]) == 6, "默认仍截 6 条")
    check(len(summary_mod._parse(raw, 100, max_points=10)["points"]) == 9, "详细档保 9 条")


def test_settings_default_depth() -> None:
    check(settings_mod.DEFAULTS["summary_depth"] == "balanced", "默认设置里是平衡档")
    check(settings_mod.validate({"summary_depth": "detailed"})["summary_depth"] == "detailed",
          "合法档位能写进去")
    try:
        settings_mod.validate({"summary_depth": "verbose"})
    except ValueError as exc:
        check("summary_depth" in str(exc), "非法档位报人话")
    else:
        raise AssertionError("非法档位应当被拒")

    before = summary_mod.settings_mod.load
    summary_mod.settings_mod.load = lambda: {"summary_depth": "detailed"}
    try:
        check(summary_mod.configured_depth() == "detailed", "读设置里的默认档")
        summary_mod.settings_mod.load = lambda: {"summary_depth": "bogus"}
        check(summary_mod.configured_depth() == "balanced", "设置写坏了回落平衡档")
        summary_mod.settings_mod.load = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        check(summary_mod.configured_depth() == "balanced", "设置读不出来也不炸")
    finally:
        summary_mod.settings_mod.load = before


def test_store_keeps_depths_apart() -> None:
    tmp = Path(__file__).resolve().parents[1] / ".onefeed" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    db = tmp / "depth-test.db"
    for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        leftover.unlink(missing_ok=True)
    store = Store(db)
    store.upsert_items([{
        "id": "bilibili:video:9", "platform": "bilibili", "kind": "video",
        "title": "测试", "text": "第一句。", "author": "作者", "cover": "",
        "url": "https://example.com/9", "published_at": int(time.time()),
        "like": 0, "comment": 0, "share": 0, "view": 0, "tags": [], "extra": {},
        "fetched_at": int(time.time()),
    }])
    store.save_summary("bilibili:video:9", {"tldr": "一句话就够", "points": []}, "brief")
    store.save_summary("bilibili:video:9", {"tldr": "平衡版", "points": [{"text": "p"}]}, "balanced")
    check(store.get_summary("bilibili:video:9", "brief")["payload"]["tldr"] == "一句话就够",
          "简洁档单独存")
    check(store.get_summary("bilibili:video:9", "balanced")["payload"]["tldr"] == "平衡版",
          "平衡档不被简洁档覆盖")
    check(store.get_summary("bilibili:video:9", "detailed") is None, "没生成的档读不到")
    store.save_summary("bilibili:video:9", {"tldr": "重写", "points": []}, "brief")
    check(store.get_summary("bilibili:video:9", "brief")["payload"]["tldr"] == "重写",
          "同档再写是覆盖")
    store.drop_summary("bilibili:video:9", "brief")
    check(store.get_summary("bilibili:video:9", "brief") is None, "按档删除")
    check(store.get_summary("bilibili:video:9", "balanced") is not None, "删一档不动另一档")
    rows = store.summarized_items(10)
    check(len(rows) == 1 and rows[0].get("summary_depth") == "balanced",
          "已总结列表只留每条最近那档")
    store.close()


def test_api_depth_round_trip() -> None:
    tmp = Path(__file__).resolve().parents[1] / ".onefeed" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    db = tmp / "depth-api.db"
    for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        leftover.unlink(missing_ok=True)
    store = Store(db)
    store.upsert_items([{
        "id": "bilibili:video:8", "platform": "bilibili", "kind": "video",
        "title": "接口测试", "text": "第一句。第二句更长一点。", "author": "作者",
        "cover": "", "url": "https://example.com/8", "published_at": int(time.time()),
        "like": 0, "comment": 0, "share": 0, "view": 0, "tags": [], "extra": {},
        "fetched_at": int(time.time()),
    }])

    def fake_boom(messages, max_tokens=900, temperature=0.5):
        raise RuntimeError("模型不在线")

    with _Patched(fake_boom):
        client = TestClient(create_app(store))
        brief = client.get("/api/item/bilibili:video:8/summary", params={"depth": "brief"}).json()
        check(brief["summary"]["depth"] == "brief", "接口按请求的档位出稿")
        check(client.get("/api/item/bilibili:video:8/summary",
                         params={"depth": "brief"}).json()["from_cache"] is True,
              "同档第二次读缓存")
        detailed = client.get("/api/item/bilibili:video:8/summary",
                              params={"depth": "detailed"}).json()
        check(detailed["summary"]["depth"] == "detailed" and detailed["from_cache"] is False,
              "换档不读另一档的缓存")
        fallback = client.get("/api/item/bilibili:video:8/summary",
                              params={"depth": "weird"}).json()
        check(fallback["summary"]["depth"] == "balanced", "不认识的档位回落平衡档")

        # 流式：meta 第一帧就得带 depth，前端靠它记住这份稿子是哪一档
        def fake_stream(messages, max_tokens=900, temperature=0.3):
            yield "content", "TLDR: 流式结论\n- 要点\n", {"name": "MiniMax", "model": "M"}

        with _PatchedStream(fake_stream):
            resp = client.get("/api/item/bilibili:video:8/summary/stream",
                              params={"depth": "detailed", "refresh": "1"})
        text = resp.text
        check('"depth": "detailed"' in text, "流式 meta/收尾带 depth")
        check('"type": "delta"' in text and '"type": "done"' in text, "流式有 delta 与 done")
    store.close()


def test_chat_messages_shape() -> None:
    src = timed((0, "第一段"), (30, "第二段"))
    host = SimpleNamespace(summary_source=lambda pid, row: src)
    store = SimpleNamespace(get_detail=lambda item_id, max_age=0: None,
                            save_detail=lambda item_id, payload: None)
    row = {"id": "bilibili:video:7", "platform": "bilibili", "title": "标题",
           "text": "", "duration": 600}
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"第{i}句"}
               for i in range(10)]
    messages = summary_mod.chat_messages(store, host, row, summary={"tldr": "结论", "points": []},
                                         history=history, question="这段讲了什么？")
    check(messages[0]["role"] == "system" and "素材里没有的" in messages[0]["content"],
          "system 规定只依据素材")
    check(messages[-1] == {"role": "user", "content": "这段讲了什么？"}, "问题在最后一条")
    body = messages[1]["content"]
    check(isinstance(body, str) and "[00:00] 第一段" in body, "素材进对话")
    check("已经给用户的总结" in body and "结论" in body, "当前这份总结也进对话")
    # messages[2] 是「看完了，问我吧」的收尾，history 紧跟其后、问题之前
    check(messages[2] == {"role": "assistant", "content": "看完了，问我吧。"},
          "素材之后先收个尾，再进对话")
    history_part = messages[3:-1]
    check(len(history_part) == summary_mod.CHAT_HISTORY_MAX, "history 截到 6 条")
    check(history_part[-1]["content"] == "第9句", "只留最近的几句")
    check(all(m["role"] in ("user", "assistant") for m in history_part), "history 只留对话角色")


def test_chat_sends_images() -> None:
    """图文条目：图要进对话，否则问「封面写了什么」只能答看不到。"""
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    detail = {"payload": {"images": ["https://cdn.example.com/1.png"] * 4,
                          "body": {"value": "<p>标签</p>"}, "media": {}}}
    store = SimpleNamespace(get_detail=lambda item_id, max_age=0: detail,
                            save_detail=lambda item_id, payload: None)
    host = SimpleNamespace(summary_source=lambda pid, row: {
        "basis": "desc", "title": "图文", "desc": "#标签", "duration": 0})
    row = {"id": "xiaohongshu:note:5", "platform": "xiaohongshu", "title": "图文",
           "text": "", "duration": 0}
    before_slot = summary_mod.media_mod.read_slot_image
    summary_mod.media_mod.read_slot_image = lambda item_id, slot, payload, pid: (png, "image/png")
    try:
        messages = summary_mod.chat_messages(store, host, row, question="封面写了什么？")
    finally:
        summary_mod.media_mod.read_slot_image = before_slot
    parts = messages[1]["content"]
    check(isinstance(parts, list), "带图时 content 是数组")
    blocks = [b for b in parts if b.get("type") == "image_url"]
    check(len(blocks) == summary_mod.CHAT_IMAGES_MAX, "对话只带前两张图")
    check(parts[0]["type"] == "text" and "别再说看不到" in parts[0]["text"],
          "文字块点明可以直接看图")


def test_chat_endpoint() -> None:
    tmp = Path(__file__).resolve().parents[1] / ".onefeed" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    db = tmp / "chat-api.db"
    for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        leftover.unlink(missing_ok=True)
    store = Store(db)
    store.upsert_items([{
        "id": "bilibili:video:6", "platform": "bilibili", "kind": "video",
        "title": "对话测试", "text": "第一句。第二句。", "author": "作者", "cover": "",
        "url": "https://example.com/6", "published_at": int(time.time()),
        "like": 0, "comment": 0, "share": 0, "view": 0, "tags": [], "extra": {},
        "fetched_at": int(time.time()),
    }])

    def fake_stream(messages, max_tokens=900, temperature=0.3):
        yield "thinking", "", {"name": "MiniMax", "model": "M"}
        yield "content", "先看", {"name": "MiniMax", "model": "M"}
        yield "content", "这一段。", {"name": "MiniMax", "model": "M"}

    client = TestClient(create_app(store))
    with _PatchedStream(fake_stream):
        resp = client.post("/api/item/bilibili:video:6/chat/stream",
                           json={"message": "这段讲了什么？"})
    text = resp.text
    check('"phase": "thinking"' in text, "先报 thinking，前几秒不空着")
    check(text.count('"type": "delta"') == 2, "逐片下发正文")
    check('"type": "done"' in text and "MiniMax" in text, "收尾带 provider")

    bad = client.post("/api/item/bilibili:video:6/chat/stream", json={"message": "  "})
    check(bad.status_code == 400, "空问题直接 400")
    check(bad.json()["error"]["code"] == "empty_message", "400 带错误码")
    missing = client.post("/api/item/bilibili:video:nope/chat/stream", json={"message": "在吗"})
    check(missing.status_code == 404, "没有这条内容 404")

    def fake_no_key(messages, max_tokens=900, temperature=0.3):
        raise RuntimeError("没有配置模型 key")
        yield  # pragma: no cover

    with _PatchedStream(fake_no_key):
        nokey = client.post("/api/item/bilibili:video:6/chat/stream", json={"message": "在吗"})
    check("还没配模型 key" in nokey.text, "没 key 时给一句能照着做的话")
    store.close()


def main() -> int:
    test_depths_are_ordered()
    test_prompt_follows_depth()
    test_detailed_keeps_more_points()
    test_settings_default_depth()
    test_store_keeps_depths_apart()
    test_api_depth_round_trip()
    test_chat_messages_shape()
    test_chat_sends_images()
    test_chat_endpoint()
    print(f"test_summary_depth: {CHECKS} 项检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
