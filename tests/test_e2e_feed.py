"""端到端冒烟：插件 → 存储 → HTTP。

跑法：python tests/test_e2e_feed.py
用两个 http 插件（zhihu-hot / juejin，免登录、快）。网络不通时跳过。
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from onefeed.app import create_app  # noqa: E402
from onefeed.store import Store  # noqa: E402
from plugin_runtime import PluginHost  # noqa: E402

PLUGINS = ("zhihu-hot", "juejin")


def main() -> int:
    host = PluginHost()
    collected = {}
    for pid in PLUGINS:
        try:
            items = host.pull(pid, limit=6)
        except Exception as exc:
            print(f"跳过 {pid}：{type(exc).__name__}: {exc}")
            continue
        if items:
            collected[pid] = items
            store_path = Path(__file__).resolve().parents[1] / ".onefeed" / "tmp" / "e2e.db"
            print(f"{pid}: {len(items)} 条  例：{items[0].title[:26]}")
    if len(collected) < 2:
        print("至少两个插件没拉到数据，跳过端到端断言")
        return 0

    tmp = ROOT / ".onefeed" / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    db = tmp / "e2e.db"
    for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        leftover.unlink(missing_ok=True)

    store = Store(db)
    total = 0
    for pid, items in collected.items():
        run_id = store.start_run(pid)
        store.upsert_items(items)
        store.finish_run(run_id, ok=True, count=len(items))
        total += len(items)

    client = TestClient(create_app(store))
    feed = client.get("/api/feed", params={"limit": 50}).json()
    assert feed["count"] == total, f"API 条数 {feed['count']} != 入库 {total}"
    platforms = {i["platform"] for i in feed["items"]}
    assert platforms == set(collected), f"平台集合不符：{platforms}"

    first = feed["items"][0]
    detail = client.get(f"/api/item/{first['id']}").json()["item"]
    assert detail["title"] == first["title"], "详情与列表不一致"

    health = client.get("/api/health").json()
    assert health["items"] == total and len(health["platforms"]) == len(collected)

    platforms_ok = all(i["title"] and i["url"] for i in feed["items"])
    assert platforms_ok, "有条目缺标题或链接"

    print(f"端到端通过：{total} 条 / {len(collected)} 平台 / 首条 {first['title'][:24]}")
    store.close_all()
    for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        leftover.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
