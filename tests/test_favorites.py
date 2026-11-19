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


def main() -> int:
    test_store_separation()
    test_api()
    print(f"✅ test_favorites.py 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
