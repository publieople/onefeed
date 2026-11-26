"""收藏夹与「稍后再看」必须是两套东西。

这两件事共用一张表会互相污染排序与时间：稍后再看是「一键丢进去、回头看」，
收藏夹是「写一句为什么留、按加入收藏夹的时间排」。这里钉住：
1. store 层两张表互不覆盖；
2. 收藏夹备注必填、重复收藏不刷新加入时间；
3. API 层 PUT/DELETE/GET 各自成立，且详情里的 favorited 与 saved 分开。
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from onefeed.app import create_app  # noqa: E402
from onefeed.store import Store  # noqa: E402

CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)


def fresh_store() -> Store:
    tmp = Path(__file__).resolve().parents[1] / ".onefeed" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    # 每个用例一个独立文件：Windows 上旧连接没关时删不掉同名库
    db = tmp / f"favorites-test-{uuid.uuid4().hex[:8]}.db"
    store = Store(db)
    now = int(time.time())
    store.upsert_items([
        {"id": f"v2ex:topic:{i}", "platform": "v2ex", "kind": "article",
         "title": f"条目 {i}", "text": "正文", "author": "a", "cover": "",
         "url": f"https://example.com/{i}", "published_at": now - i * 60,
         "like": 0, "comment": 0, "share": 0, "view": 0, "tags": [], "extra": {},
         "fetched_at": now}
        for i in (1, 2)
    ])
    return store


def test_store_separation() -> None:
    store = fresh_store()
    fav = store.favorite_item("v2ex:topic:1", "留着写稿引用")
    check(fav["favorited"] is True and fav["note"] == "留着写稿引用", "收藏夹写入备注")
    check(store.get_mark("v2ex:topic:1")["saved"] is False, "收藏夹不动稍后再看")

    store.mark_item("v2ex:topic:1", saved=True)
    check(store.get_favorite("v2ex:topic:1")["favorited"] is True, "稍后再看不动收藏夹")

    first = store.get_favorite("v2ex:topic:1")
    time.sleep(0.05)
    again = store.favorite_item("v2ex:topic:1", "改一下备注")
    check(again["created_at"] == first["created_at"], "重复收藏不刷新加入时间")
    check(again["note"] == "改一下备注", "重复收藏只更新备注")

    listed = store.favorite_items()
    check(len(listed) == 1 and listed[0]["favorite_note"] == "改一下备注", "列表带备注")
    check(listed[0]["saved"] is True, "列表保留稍后再看状态（两条数据都不丢）")

    check(store.unfavorite_item("v2ex:topic:1") is True, "能移出收藏夹")
    check(store.get_favorite("v2ex:topic:1")["favorited"] is False, "移出后读不到收藏")
    check(store.get_mark("v2ex:topic:1")["saved"] is True, "移出收藏夹不影响稍后再看")
    check(store.unfavorite_item("v2ex:topic:1") is False, "重复移出返回 False")


def test_prune_keeps_saved_and_favorites() -> None:
    """收藏和稍后再看不能被保留期清掉；被删条目的从表行不能留孤儿。"""
    store = fresh_store()
    old = int(time.time()) - 40 * 86400
    store.upsert_items([
        {"id": "v2ex:old-saved", "platform": "v2ex", "kind": "article",
         "title": "旧的稍后再看", "text": "", "author": "a", "cover": "",
         "url": "https://example.com/old-saved", "published_at": old,
         "fetched_at": old, "like": 0, "comment": 0, "share": 0,
         "view": 0, "tags": [], "extra": {}},
        {"id": "v2ex:old-fav", "platform": "v2ex", "kind": "article",
         "title": "旧的收藏", "text": "", "author": "a", "cover": "",
         "url": "https://example.com/old-fav", "published_at": old,
         "fetched_at": old, "like": 0, "comment": 0, "share": 0,
         "view": 0, "tags": [], "extra": {}},
        {"id": "v2ex:old-plain", "platform": "v2ex", "kind": "article",
         "title": "旧的普通条目", "text": "", "author": "a", "cover": "",
         "url": "https://example.com/old-plain", "published_at": old,
         "fetched_at": old, "like": 0, "comment": 0, "share": 0,
         "view": 0, "tags": [], "extra": {}},
    ])
    store.mark_item("v2ex:old-saved", saved=True)
    store.favorite_item("v2ex:old-fav", "留着")
    store.mark_item("v2ex:old-plain", read=True)
    store.save_detail("v2ex:old-saved", {"marker": "saved"})
    store.save_detail("v2ex:old-plain", {"marker": "plain"})
    store.save_summary("v2ex:old-plain", {"tldr": "plain"})

    removed = store.prune(keep_days=14)

    check(removed == 1, f"只删普通旧条目（实际 {removed}）")
    check(store.get_item("v2ex:old-saved") is not None, "稍后再看的条目保留")
    check(store.get_item("v2ex:old-fav") is not None, "收藏的条目保留")
    check(store.get_item("v2ex:old-plain") is None, "普通旧条目被清掉")
    check(store.get_detail("v2ex:old-saved") is not None, "保留条目的详情跟着保留")
    check(store.get_detail("v2ex:old-plain") is None, "被删条目的详情清掉")
    check(store.get_summary("v2ex:old-plain") is None, "被删条目的总结清掉")
    check([r["id"] for r in store.saved_items()] == ["v2ex:old-saved"],
          "稍后再看列表仍能查到")
    check([r["id"] for r in store.favorite_items()] == ["v2ex:old-fav"],
          "收藏夹列表仍能查到")
    orphan_marks = store.conn.execute(
        "SELECT COUNT(*) FROM item_marks WHERE item_id = ?",
        ("v2ex:old-plain",)).fetchone()[0]
    check(orphan_marks == 0, "被删条目的标记行一起清掉")


def test_api() -> None:
    store = fresh_store()
    client = TestClient(create_app(store))
    item = "v2ex:topic:1"

    empty = client.get("/api/favorites").json()
    check(empty["count"] == 0, "一开始收藏夹是空的")

    bad = client.put(f"/api/favorites/{item}", json={"note": "   "})
    check(bad.status_code == 400, "没写备注拒绝收藏")
    check(bad.json()["error"]["code"] == "need_note", "错误码是 need_note")

    ok = client.put(f"/api/favorites/{item}", json={"note": "下周做视频用"})
    check(ok.status_code == 200 and ok.json()["favorite"]["note"] == "下周做视频用", "写备注收藏成功")

    status = client.get(f"/api/favorites/{item}").json()
    check(status["favorited"] is True, "单条状态可查")

    listed = client.get("/api/favorites").json()
    check(listed["count"] == 1 and listed["items"][0]["favorite_note"] == "下周做视频用",
          "列表里带备注")

    detail = client.get(f"/api/item/{item}").json()
    item_row = detail.get("item") or {}
    check(item_row.get("favorited") is True and item_row.get("saved") is False,
          "详情里 favorited 与 saved 分开")

    gone = client.delete(f"/api/favorites/{item}").json()
    check(gone["ok"] is True and gone["removed"] is True, "DELETE 能移出")
    check(client.get(f"/api/favorites/{item}").json()["favorited"] is False, "移出后状态变 false")

    missing = client.put("/api/favorites/v2ex:topic:999", json={"note": "x"})
    check(missing.status_code == 404, "不存在的条目不能收藏")


def test_paging() -> None:
    """右栏列表不能只看到第一页：偏移量要继续往下翻，且不能重复。"""
    store = fresh_store()
    now = int(time.time())
    store.upsert_items([
        {"id": f"v2ex:topic:{i}", "platform": "v2ex", "kind": "article",
         "title": f"分页条目 {i}", "text": "正文", "author": "a", "cover": "",
         "url": f"https://example.com/page/{i}", "published_at": now - i * 60,
         "like": 0, "comment": 0, "share": 0, "view": 0, "tags": [], "extra": {},
         "fetched_at": now}
        for i in (3, 4, 5, 6)
    ])
    for i in range(1, 7):
        store.favorite_item(f"v2ex:topic:{i}", f"第 {i} 条备注")
        store.save_summary(f"v2ex:topic:{i}", {"tldr": f"第 {i} 条总结"})

    client = TestClient(create_app(store))
    first = client.get("/api/favorites?limit=2&offset=0").json()
    second = client.get("/api/favorites?limit=2&offset=2").json()
    check(len(first["items"]) == 2 and first["has_more"] is True, "收藏夹第一页带 has_more")
    check(len(second["items"]) == 2, "收藏夹第二页也是两条")
    check({row["id"] for row in first["items"]}.isdisjoint(
        {row["id"] for row in second["items"]}), "两页不重复")
    tail = client.get("/api/favorites?limit=2&offset=4").json()
    check(len(tail["items"]) == 2, "收藏夹最后一页取到剩下的两条")
    check(tail["has_more"] is False, "取完以后 has_more 变 false")
    check(client.get("/api/favorites?limit=2&offset=6").json()["items"] == [], "超出范围返回空")

    summaries = client.get("/api/agent/summaries?limit=3&offset=0").json()
    check(len(summaries["items"]) == 3 and summaries["has_more"] is True, "总结第一页带 has_more")
    rest = client.get("/api/agent/summaries?limit=3&offset=3").json()
    check(len(rest["items"]) == 3 and rest["has_more"] is False, "总结第二页取完")


def main() -> int:
    test_store_separation()
    test_prune_keeps_saved_and_favorites()
    test_api()
    test_paging()
    print(f"✅ test_favorites.py 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
