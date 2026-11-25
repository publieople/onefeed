"""关注流：独立同步器、分页、失败隔离与 API。

关注流的价值不在「多一条列表」，而在它和主信息流互不污染：
- 同一内容可以同时在信息流和关注流各有一行，但 items 只有一条；
- 没有发布时间的笔记按第一次看到的时间排，并标 time_estimated；
- 某个平台挂了不能拖垮别的平台，也不能让关注页永远显示「正在同步」。
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from onefeed.app import create_app  # noqa: E402
from onefeed.following import ACCOUNTS_FEED, FOLLOWING_FEED, AccountsRunner, FollowingRunner  # noqa: E402
from onefeed.store import Store  # noqa: E402
from models import Item  # noqa: E402


def make_store() -> Store:
    return Store(Path(tempfile.mkdtemp(prefix="onefeed-following-db-")) / "test.db")


def item(item_id: str, platform: str, published_at: int = 0, author_id: str = "") -> dict:
    return {
        "id": item_id,
        "platform": platform,
        "kind": "video" if platform == "bilibili" else "article",
        "title": "标题 " + item_id,
        "text": "",
        "author": "作者 " + (author_id or platform),
        "author_id": author_id,
        "cover": "",
        "url": "https://example.com/" + item_id,
        "published_at": published_at,
        "fetched_at": int(time.time()),
    }


class FakeHost:
    demo = False

    def __init__(self, items_by_plugin: dict[str, list[dict]], fail: tuple[str, ...] = (), delay: float = 0.0,
                 accounts_by_plugin: dict[str, list[dict]] | None = None,
                 posts_by_plugin: dict[str, list[dict]] | None = None):
        self.items_by_plugin = items_by_plugin
        self.accounts_by_plugin = accounts_by_plugin or {}
        self.posts_by_plugin = posts_by_plugin or {}
        self.fail = set(fail)
        self.delay = delay
        self.calls: list[tuple[str, str]] = []
        self.account_calls: list[tuple[str, str | None]] = []
        self.post_calls: list[tuple[str, str, str | None]] = []
        self.errors: list[str] = []

    def discover(self):
        return [
            SimpleNamespace(id=pid, name=pid.upper(), features=["following_accounts", "author_posts"],
                            feed_ids=lambda: ["recommend", "following"])
            for pid in self.items_by_plugin
        ]

    def pull(self, plugin_id, feed_id=None, limit=20, cursor=None):
        self.calls.append((plugin_id, str(feed_id or "")))
        if self.delay:
            time.sleep(self.delay)
        if plugin_id in self.fail:
            raise RuntimeError("平台挂了")
        return list(self.items_by_plugin.get(plugin_id, []))[:limit]

    def following_accounts(self, plugin_id, cursor=None, limit=200):
        self.account_calls.append((plugin_id, cursor))
        if self.delay:
            time.sleep(self.delay)
        if plugin_id in self.fail:
            raise RuntimeError("平台挂了")
        return {"items": list(self.accounts_by_plugin.get(plugin_id, []))[:limit], "next": None}

    def author_profile(self, plugin_id, account_id):
        return {"name": "远端作者 " + account_id, "avatar": "https://example.com/a.jpg",
                "bio": "简介", "url": "https://example.com/u/" + account_id,
                "following": 12, "follower": 34}

    def author_posts(self, plugin_id, account_id, cursor=None, limit=20):
        self.post_calls.append((plugin_id, account_id, cursor))
        return {"items": list(self.posts_by_plugin.get(plugin_id, []))[:limit], "next": None}


def account(account_id: str, name: str = "") -> dict:
    return {"account_id": account_id, "name": name or "账号 " + account_id,
            "avatar": "https://example.com/" + account_id + ".jpg",
            "url": "https://example.com/u/" + account_id,
            "bio": "简介 " + account_id, "relation": "following"}


def wait_idle(runner: FollowingRunner, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    while runner.running() and time.time() < deadline:
        time.sleep(0.02)
    assert not runner.running(), "关注流后台线程没有按时收尾"


def test_mark_page_and_orphans():
    store = make_store()
    now = int(time.time())
    rows = [
        item("bilibili:1", "bilibili", now - 10, "up1"),
        item("bilibili:2", "bilibili", now - 20, "up1"),
        item("zhihu:1", "zhihu", now - 30, "author1"),
        item("xiaohongshu:1", "xiaohongshu", 0, "xhs1"),
    ]
    store.upsert_items(rows)
    assert store.mark_feed_items(rows) == 4
    # 重复标记只更新 last_seen_at，不能把 first_seen_at 冲掉
    before = {r["id"]: r for r in store.following_page(limit=10)[0]}
    time.sleep(1.05)
    assert store.mark_feed_items(rows[:1]) == 1
    after = {r["id"]: r for r in store.following_page(limit=10)[0]}
    assert after["bilibili:1"]["feed_first_seen_at"] == before["bilibili:1"]["feed_first_seen_at"]
    assert after["bilibili:1"]["feed_last_seen_at"] > before["bilibili:1"]["feed_last_seen_at"]

    page, nxt = store.following_page(platforms=["bilibili"], limit=1)
    assert len(page) == 1 and page[0]["id"] == "bilibili:1"
    assert nxt, "两条里取一条，必须给下一页游标"
    page2, nxt2 = store.following_page(platforms=["bilibili"], limit=1, cursor=nxt)
    assert page2 and page2[0]["id"] == "bilibili:2" and nxt2 is None

    all_rows = store.following_page(limit=10)[0]
    xhs = [r for r in all_rows if r["id"] == "xiaohongshu:1"][0]
    assert xhs["time_estimated"] is True, "没有发布时间要如实标成估的"
    assert all_rows[0]["following"] is True
    assert {r["platform"]: r["count"] for r in store.following_counts()} == {
        "bilibili": 2, "zhihu": 1, "xiaohongshu": 1,
    }

    # 孤儿行：item 被删掉后，prune 要把它从关注流里也清掉，不能虚高计数
    store.conn.execute("DELETE FROM items WHERE id = ?", ("zhihu:1",))
    store.conn.commit()
    store.prune(keep_days=14)
    assert store.following_count() == 3
    assert store.following_page(limit=10)[0][0]["id"] != "zhihu:1"


def test_runner_syncs_marks_and_respects_cooldown():
    store = make_store()
    now = int(time.time())
    host = FakeHost({
        "bilibili": [item("bilibili:1", "bilibili", now - 5, "up1")],
        "zhihu": [item("zhihu:1", "zhihu", now - 10, "author1")],
    })
    runner = FollowingRunner(store, host=host, limit=10)
    assert set(runner.platform_ids()) == {"bilibili", "zhihu"}
    ok, state = runner.trigger(force=True)
    assert ok and state["running"] and state["total"] == 2
    wait_idle(runner)
    snap = runner.snapshot()
    assert snap["phase"] == "done" and snap["new_total"] == 2
    assert all(feed == FOLLOWING_FEED for _, feed in host.calls)
    assert store.following_count() == 2
    stats = store.following_run_stats()
    assert stats["bilibili"]["last_ok"] is True
    assert stats["bilibili"]["last_ok_at"] > 0
    assert stats["zhihu"]["count"] == 1

    again, cooled = runner.trigger()
    assert again is False and "冷却" in cooled["error"]


def test_failure_isolation_and_cancel():
    store = make_store()
    now = int(time.time())
    host = FakeHost({
        "bilibili": [item("bilibili:1", "bilibili", now - 5)],
        "zhihu": [item("zhihu:1", "zhihu", now - 10)],
    }, fail=("bilibili",))
    runner = FollowingRunner(store, host=host, limit=10)
    assert runner.trigger(force=True)[0]
    wait_idle(runner)
    snap = runner.snapshot()
    assert snap["phase"] == "partial" and snap["plugins"]["bilibili"]["status"] == "failed"
    assert snap["plugins"]["zhihu"]["status"] == "ok"
    assert store.following_count() == 1, "失败平台不能把成功平台的条目一起丢掉"
    stats = store.following_run_stats()
    assert stats["bilibili"]["last_ok"] is False and "平台挂了" in stats["bilibili"]["error"]

    # 取消：只停排队中的平台，不打断正在跑的那个
    slow = FakeHost({
        "bilibili": [item("bilibili:1", "bilibili", now - 5)],
        "zhihu": [item("zhihu:1", "zhihu", now - 10)],
        "xiaohongshu": [item("xiaohongshu:1", "xiaohongshu", 0)],
    }, delay=0.12)
    runner2 = FollowingRunner(make_store(), host=slow, limit=10)
    assert runner2.trigger(force=True, owner="run-x")[0]
    assert runner2.cancel(owner="another") is False, "别人的 owner 不能停这一轮"
    assert runner2.cancel(owner="run-x") is True
    wait_idle(runner2)
    snap2 = runner2.snapshot()
    assert snap2["phase"] == "cancelled"
    assert snap2["cancel_requested"] is False
    cancelled = [p for p in snap2["plugins"].values() if p["status"] == "cancelled"]
    assert cancelled, "取消后排队中的平台要标成 cancelled"


def test_api_following_and_layout_setting():
    store = make_store()
    now = int(time.time())
    seeded = [item("bilibili:1", "bilibili", now - 5, "up1"),
              item("zhihu:1", "zhihu", now - 10, "author1")]
    store.upsert_items(seeded)
    store.mark_feed_items(seeded)
    client = TestClient(create_app(store))
    client.app.state.following = FollowingRunner(store, host=FakeHost({
        "bilibili": [item("bilibili:2", "bilibili", now - 1, "up1")],
        "zhihu": [item("zhihu:2", "zhihu", now - 2, "author1")],
    }), limit=10)

    resp = client.get("/api/following")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2 and body["count"] == 2
    assert {i["id"] for i in body["items"]} == {"bilibili:1", "zhihu:1"}
    assert body["platforms"][0]["platform"] == "bilibili"
    assert body["syncing"] is False

    got = client.get("/api/following", params={"platform": "bilibili"})
    assert [i["id"] for i in got.json()["items"]] == ["bilibili:1"]

    started = client.post("/api/following/refresh", json={"force": True})
    assert started.status_code == 200 and started.json()["ok"] is True
    wait_idle(client.app.state.following)
    body2 = client.get("/api/following").json()
    assert body2["total"] == 4
    assert client.get("/api/following/progress").json()["state"]["phase"] == "done"

    saved = client.put("/api/settings", json={"following_layout": "compact"})
    assert saved.status_code == 200
    assert client.get("/api/settings").json()["settings"]["following_layout"] == "compact"
    bad = client.put("/api/settings", json={"following_layout": "masonry"})
    assert bad.status_code == 400


def test_accounts_runner_and_api():
    store = make_store()
    host = FakeHost(
        {"bilibili": [], "zhihu": []},
        accounts_by_plugin={"bilibili": [account("up1"), account("up2")],
                            "zhihu": [account("z1")]},
    )
    runner = AccountsRunner(store, host=host)
    ok, state = runner.trigger(force=True)
    assert ok and state["running"] and state["total"] == 2
    wait_idle(runner)
    assert runner.snapshot()["feed"] == ACCOUNTS_FEED
    assert {r["account_id"] for r in store.following_accounts(platform="bilibili")} == {"up1", "up2"}
    assert store.following_account_counts()[0]["platform"] in ("bilibili", "zhihu")

    # 第二轮只返回 up2：up1 标记 inactive，不删；名单为空时不动旧记录
    host.accounts_by_plugin = {"bilibili": [account("up2")]}
    assert runner.trigger(force=True)[0]
    wait_idle(runner)
    active = {r["account_id"] for r in store.following_accounts(platform="bilibili")}
    assert active == {"up2"}
    assert len(store.following_accounts(platform="bilibili", active=None)) == 2
    before = len(store.following_accounts(platform="bilibili", active=None))
    host.accounts_by_plugin = {"bilibili": []}
    assert runner.trigger(force=True)[0]
    wait_idle(runner)
    assert len(store.following_accounts(platform="bilibili", active=None)) == before

    client = TestClient(create_app(store))
    client.app.state.accounts = runner
    body = client.get("/api/following/accounts", params={"platform": "bilibili"}).json()
    assert body["total"] == 1 and body["accounts"][0]["account_id"] == "up2"
    assert body["counts"] and body["platforms"]
    found = client.get("/api/following/accounts", params={"q": "账号 up2"}).json()
    assert found["total"] == 1
    started = client.post("/api/following/accounts/refresh", json={"force": True})
    assert started.status_code == 200 and started.json()["ok"] is True
    wait_idle(runner)
    assert client.get("/api/following/accounts/progress").json()["state"]["phase"] in ("done", "cancelled")


def test_author_page_and_remote_posts():
    store = make_store()
    now = int(time.time())
    seeded = item("bilibili:old", "bilibili", now - 100, "up1")
    store.upsert_items([seeded])
    host = FakeHost(
        {"bilibili": [seeded]},
        posts_by_plugin={"bilibili": [
            # 同一条内容已经在主信息流可见：作者页再抓一次不能把它藏起来
            Item(
                id="bilibili:old", platform="bilibili", raw_id="BVold", title="作者的老视频",
                kind="video", author="作者 up1", author_id="up1", url="https://example.com/BVold",
                published_at=now - 100,
            ),
            Item(
                id="bilibili:new", platform="bilibili", raw_id="BVnew", title="作者的新视频",
                kind="video", author="作者 up1", author_id="up1", url="https://example.com/BVnew",
                published_at=now - 5,
            ),
        ]},
    )
    client = TestClient(create_app(store))
    client.app.state.accounts = AccountsRunner(store, host=host)
    client.app.state.refresher.host = host

    body = client.get("/api/authors/bilibili/up1").json()
    assert body["profile"]["name"] == "作者 up1"
    assert body["profile"]["following"] is False
    assert body["total"] == 1 and [i["id"] for i in body["items"]] == ["bilibili:old"]
    assert body["remote_supported"] is True

    fetched = client.post("/api/authors/bilibili/up1/fetch", json={}).json()
    assert fetched["ok"] is True and fetched["fetched"] == 2 and fetched["added"] == 1
    after = client.get("/api/authors/bilibili/up1").json()
    assert after["total"] == 2
    assert [i["id"] for i in after["items"]][0] == "bilibili:new"
    assert all(i["author_only"] for i in after["items"] if i["id"] == "bilibili:new")
    # 作者页补回来的历史内容，不能出现在主信息流/关注流；
    # 但本来就可见的那条不能被作者页顺手标成 author_only。
    assert store.count() == 1
    assert store.following_count() == 0
    assert store.get_item("bilibili:old")["author_only"] is False

    # 只是点进来看一眼的陌生人，不能被写进关注名单
    ghost = client.get("/api/authors/bilibili/ghost").json()
    assert ghost["profile"]["name"] == "远端作者 ghost"
    assert ghost["profile"]["following"] is False
    assert store.following_accounts(platform="bilibili", active=None) == []


def main() -> int:
    test_mark_page_and_orphans()
    test_runner_syncs_marks_and_respects_cooldown()
    test_failure_isolation_and_cancel()
    test_api_following_and_layout_setting()
    test_accounts_runner_and_api()
    test_author_page_and_remote_posts()
    print("关注流 6 组检查全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
