"""T30 验收：只读 HTTP API。

跑法：python tests/test_api.py
用 starlette TestClient（进程内，不占端口），临时库 + 6 条样例数据。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from onefeed.app import WEB_DIST, create_app  # noqa: E402
from onefeed.store import Store  # noqa: E402

CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)


def seed() -> list[dict]:
    now = int(time.time())
    rows = []
    for i in range(6):
        rows.append({
            "id": f"{'bilibili' if i % 2 == 0 else 'xiaohongshu'}:{i}",
            "platform": "bilibili" if i % 2 == 0 else "xiaohongshu",
            "kind": "video" if i % 2 == 0 else "images",
            "title": f"标题 {i}", "text": "", "author": f"作者{i}",
            "cover": f"https://example.com/{i}.jpg",
            "url": f"https://example.com/p/{i}",
            "published_at": now - i * 3600,
            "like": 10 * i, "comment": i, "share": 0, "view": 100 * i,
            "tags": [], "extra": {}, "fetched_at": now,
        })
    return rows


def main() -> int:
    tmp = Path(__file__).resolve().parents[1] / ".onefeed" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    db = tmp / "api-test.db"
    for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        leftover.unlink(missing_ok=True)

    if True:
        store = Store(db)
        store.upsert_items(seed())
        store.upsert_plugin("bilibili", "0.3.0", sha256="x", source="registry")
        store.finish_run(store.start_run("bilibili"), ok=True, count=3)
        client = TestClient(create_app(store))

        # health
        h = client.get("/api/health")
        check(h.status_code == 200, "health 200")
        body = h.json()
        check(body["ok"] is True and body["items"] == 6, "health 报条目数")
        check({p["platform"] for p in body["platforms"]} == {"bilibili", "xiaohongshu"},
              "health 报平台统计")

        # feed 默认
        f = client.get("/api/feed")
        check(f.status_code == 200, "feed 200")
        feed = f.json()
        check(feed["count"] == 6 and len(feed["items"]) == 6, "feed 返回全部")
        check(feed["items"][0]["id"].endswith(":0"), "feed 默认按时间倒序")
        check(isinstance(feed["items"][0]["stats"], dict), "条目带 stats")

        # 平台过滤（逗号分隔多值）
        fp = client.get("/api/feed", params={"platform": "bilibili"}).json()
        check(fp["count"] == 3 and all(i["platform"] == "bilibili" for i in fp["items"]),
              "按平台过滤")
        fm = client.get("/api/feed", params={"platform": "bilibili,xiaohongshu"}).json()
        check(fm["count"] == 6, "平台逗号分隔多值")

        # kind 过滤
        fk = client.get("/api/feed", params={"kind": "images"}).json()
        check(fk["count"] == 3 and all(i["kind"] == "images" for i in fk["items"]), "按 kind 过滤")

        # 排序
        fe = client.get("/api/feed", params={"sort": "engagement"}).json()
        check(fe["items"][0]["stats"]["like"] >= fe["items"][-1]["stats"]["like"], "engagement 排序")
        bad = client.get("/api/feed", params={"sort": "random"})
        check(bad.status_code == 422, "非法排序 422")
        check(bad.json()["error"]["code"] == "bad_sort", "非法排序错误码")

        # 分页
        all_ids = [i["id"] for i in client.get("/api/feed").json()["items"]]
        p1 = client.get("/api/feed", params={"limit": 4}).json()
        check(len(p1["items"]) == 4 and p1["next"], "第一页 4 条 + next")
        p2 = client.get("/api/feed", params={"limit": 4, "cursor": p1["next"]}).json()
        check([i["id"] for i in p1["items"]] + [i["id"] for i in p2["items"]] == all_ids,
              "两页拼起来等于全集（不重不漏）")
        check(p2["next"] is None, "到底 next 为 None")
        check(client.get("/api/feed", params={"limit": 0}).status_code == 422, "limit 下界校验")
        check(client.get("/api/feed", params={"limit": 101}).status_code == 422, "limit 上界校验")
        check(client.get("/api/feed", params={"limit": 0}).json()["error"]["code"] == "bad_request",
              "参数错误码 bad_request")

        # 详情
        one = client.get("/api/item/bilibili:0")
        check(one.status_code == 200 and one.json()["item"]["title"] == "标题 0", "详情 200")
        missing = client.get("/api/item/nope:404")
        check(missing.status_code == 404, "详情不存在 404")
        check(missing.json()["error"]["code"] == "item_not_found", "详情 404 错误码")

        # plugins / runs
        check(len(client.get("/api/plugins").json()["installed"]) == 1, "插件列表")
        r = client.get("/api/runs").json()["runs"]
        check(len(r) == 1 and r[0]["ok"] == 1, "轮次列表")

        # 前端未构建时的根路径
        if not WEB_DIST.is_dir():
            root = client.get("/")
            check(root.status_code == 200 and "hint" in root.json(), "无前端时根路径给提示")

        store.close_all()
        for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
            leftover.unlink(missing_ok=True)

    print(f"T30 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
