"""T50–T55 验收：AI 总结的解析、素材拼装、规则兜底、缓存与接口。

跑法：
    python tests/test_summary.py
不联网：模型调用全部替换成假函数，只验「素材怎么拼、模型输出怎么收、模型挂了怎么办」。
"""
from __future__ import annotations

import json as jsonlib
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


def timed(*pairs) -> dict:
    return {"basis": "transcript", "title": "标题", "duration": 600,
            "transcript": {"lines": [{"t": t, "text": text} for t, text in pairs]}}


class _Patched:
    """把 ai.complete 换成假函数，退出时还原。"""

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


def test_mmss() -> None:
    check(summary_mod._mmss(0) == "00:00", "0 秒补零")
    check(summary_mod._mmss(75) == "01:15", "75 秒写成 01:15")
    check(summary_mod._mmss(-5) == "00:00", "负数按 0 处理")


def test_parse() -> None:
    fence = "```"
    raw = fence + 'json\n{"tldr":"结论","points":[{"t":180,"text":"三条要点"},{"t":"6:20","text":"六分二十"},{"t":null,"text":"没有时间"},{"t":99999,"text":"越界的时间"}],"caveat":"注意"}\n' + fence
    parsed = summary_mod._parse(raw, 600)
    check(parsed is not None, "带代码围栏的 JSON 也能解析")
    check(parsed["tldr"] == "结论", "解析出 tldr")
    check([p.get("t") for p in parsed["points"]] == [180, 380, None, None],
          "t 支持秒与 mm:ss，越界丢掉")
    check(parsed["caveat"] == "注意", "解析出 caveat")

    only_points = summary_mod._parse('{"points":["一条原话"]}', 0)
    check(only_points is not None and only_points["tldr"] == "", "只有 points 也收")
    check(summary_mod._parse("模型胡言乱语", 0) is None, "没有 JSON 返回 None")
    check(summary_mod._parse('{"tldr":"","points":[]}', 0) is None, "空结果返回 None")

    many = {"tldr": "x", "points": [{"t": None, "text": f"p{i}"} for i in range(9)]}
    cap = summary_mod._parse(jsonlib.dumps(many), 100)
    check(len(cap["points"]) == summary_mod.POINT_MAX, "要点最多 6 条")


def test_material() -> None:
    src = timed((0, "开场白"), (65, "第二段"))
    src["desc"] = "<p>简介<em>文字</em></p>"
    src["official"] = "平台总结"
    src["comments"] = [{"text": "热评", "like": 12}]
    text = summary_mod._material(src, "transcript")
    check("标题：标题" in text, "素材带标题")
    check("简介：简介 文字" in text, "简介去 HTML 标签")
    check("[00:00] 开场白" in text and "[01:05] 第二段" in text, "字幕行带时间点")
    check("热评" not in text, "basis 是字幕时不塞热评")

    desc_only = summary_mod._material({"title": "t", "desc": "d", "comments": [{"text": "热", "like": 3}]}, "desc")
    check("热评（只用来判断这条在讲什么）" in desc_only, "basis 是简介时用热评帮判断")


def test_rule_summary() -> None:
    src = timed(*[(i * 30, f"第{i}段内容") for i in range(12)])
    row = SimpleNamespace(title="标题", text="", duration=600)
    out = summary_mod._rule_summary(src, "transcript", row)
    check(len(out["points"]) == summary_mod.POINT_MAX, "规则兜底也给满 6 条")
    check(out["points"][0]["t"] == 0, "规则兜底保留时间点")
    check("模型暂时不可用" in out["caveat"], "规则兜底会说明是摘原句")

    plain = summary_mod._rule_summary(
        {"title": "只有标题", "desc": "第一句话说得长一点。第二句也不短。"}, "desc", row)
    check(plain["tldr"] == "只有标题", "没有字幕时用标题当结论")
    check(len(plain["points"]) >= 1 and plain["points"][0]["text"].startswith("第一句话说得长一点"),
          "没有字幕时按句子摘（太短的句子丢掉）")


def test_build_llm_and_fallback() -> None:
    src = timed((0, "开场"), (120, "中段"), (600, "结尾"))
    host = SimpleNamespace(summary_source=lambda pid, row: src)
    row = {"id": "bilibili:video:1", "platform": "bilibili", "title": "标题",
           "text": "", "duration": 600}
    store = SimpleNamespace(get_detail=lambda item_id, max_age=0: None)

    def fake_ok(messages, max_tokens=900, temperature=0.5):
        return ('{"tldr":"看懂了","points":[{"t":120,"text":"中段"}],"caveat":""}',
                {"name": "MiniMax", "model": "MiniMax-M3.1-Flash"})

    with _Patched(fake_ok):
        out = summary_mod.build(store, host, row)
    check(out["engine"] == "llm" and out["provider"] == "MiniMax", "模型可用时记 provider")
    check(out["basis"] == "transcript" and out["basis_text"] == "完整字幕", "basis 透传成中文")
    check(out["points"][0]["t"] == 120 and out["tldr"] == "看懂了", "用模型给的要点")
    check(out["source_chars"] > 0 and out["ms"] >= 0, "带素材字数与耗时")
    check(out["generated_at"] > 0, "带生成时间")

    def fake_boom(messages, max_tokens=900, temperature=0.5):
        raise RuntimeError("401 unauthorized")

    with _Patched(fake_boom):
        fallback = summary_mod.build(store, host, row)
    check(fallback["engine"] == "rules", "模型报错退回规则")
    check(fallback["provider"] == "" and fallback["model"] == "", "规则兜底不编 provider")
    check(len(fallback["points"]) >= 1, "规则兜底仍有要点")

    no_host = SimpleNamespace(summary_source=lambda pid, item: None)
    plain = summary_mod.build(store, no_host, dict(row, text="第一条。第二条更长一点。"))
    check(plain["basis"] == "desc" and plain["basis_text"] == "标题与简介", "没有插件素材时按简介兜底")

    empty_host = SimpleNamespace(summary_source=lambda pid, item: {"basis": "transcript", "title": "",
                                                                  "desc": "", "transcript": {"lines": []}})
    try:
        summary_mod.build(store, empty_host, {"id": "x", "platform": "x", "title": "", "text": ""})
    except RuntimeError as exc:
        check("没有能读的正文" in str(exc), "完全没素材时报一句人话")
    else:
        raise AssertionError("空素材应当报错")


def test_store_and_api() -> None:
    tmp = Path(__file__).resolve().parents[1] / ".onefeed" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    db = tmp / "summary-test.db"
    for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        leftover.unlink(missing_ok=True)

    store = Store(db)
    store.upsert_items([{
        "id": "bilibili:video:1", "platform": "bilibili", "kind": "video",
        "title": "测试条目", "text": "第一句。第二句更长一点。", "author": "作者",
        "cover": "", "url": "https://example.com/1", "published_at": int(time.time()),
        "like": 0, "comment": 0, "share": 0, "view": 0, "tags": [], "extra": {},
        "fetched_at": int(time.time()),
    }])

    store.save_summary("bilibili:video:1", {"tldr": "旧结论", "points": []})
    first = store.get_summary("bilibili:video:1")
    check(first is not None and first["payload"]["tldr"] == "旧结论", "总结能写能读")
    store.save_summary("bilibili:video:1", {"tldr": "新结论", "points": [{"text": "p"}]})
    again = store.get_summary("bilibili:video:1")
    check(again["payload"]["tldr"] == "新结论" and len(again["payload"]["points"]) == 1,
          "同一条再写是覆盖")
    store.drop_summary("bilibili:video:1")
    check(store.get_summary("bilibili:video:1") is None, "drop 之后读不到")

    def fake_boom(messages, max_tokens=900, temperature=0.5):
        raise RuntimeError("模型不在线")

    with _Patched(fake_boom):
        client = TestClient(create_app(store))
        first = client.get("/api/item/bilibili:video:1/summary")
        check(first.status_code == 200, "总结接口 200")
        body = first.json()
        check(body["ok"] is True and body["from_cache"] is False, "首次生成不回缓存")
        check(body["summary"]["engine"] == "rules", "模型挂了接口仍然出结果")
        check(body["fetched_at"] > 0, "返回缓存时间")

        second = client.get("/api/item/bilibili:video:1/summary").json()
        check(second["from_cache"] is True and second["summary"]["tldr"] == body["summary"]["tldr"],
              "第二次读缓存")

        forced = client.get("/api/item/bilibili:video:1/summary", params={"refresh": "1"}).json()
        check(forced["from_cache"] is False, "refresh=1 绕过缓存")

        missing = client.get("/api/item/bilibili:video:nope/summary")
        check(missing.status_code == 404, "没有这条内容返回 404")
        check(missing.json()["error"]["code"] == "item_not_found", "404 带错误码")

    store.close()


def main() -> int:
    test_mmss()
    test_parse()
    test_material()
    test_rule_summary()
    test_build_llm_and_fallback()
    test_store_and_api()
    print(f"✅ test_summary: {CHECKS} 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())