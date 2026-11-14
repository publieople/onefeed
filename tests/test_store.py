"""T29 验收：SQLite 存储层。

跑法（不依赖 pytest）：
    python tests/test_store.py
只想看结果不想跑全部：加 --verbose。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onefeed.store import Store, decode_cursor, encode_cursor  # noqa: E402

VERBOSE = "--verbose" in sys.argv
CHECKS = 0


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


def sample(n: int = 5) -> list[dict]:
    now = int(time.time())
    items = []
    for i in range(n):
        items.append({
            "id": f"demo:item{i}",
            "platform": "demo",
            "kind": "video" if i % 2 == 0 else "images",
            "title": f"样例标题 {i}",
            "text": "正文" * 3,
            "author": f"作者{i}",
            "cover": f"https://example.com/{i}.jpg",
            "images": [f"https://example.com/{i}a.jpg"],
            "url": f"https://example.com/p/{i}",
            "published_at": now - i * 60,
            "like": 100 - i,
            "comment": i,
            "share": 0,
            "view": 1000 * (i + 1),
            "tags": ["a", "b"],
            "extra": {"src": "test"},
            "fetched_at": now,
        })
    return items


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "test.db"
        store = Store(db)

        # 建表与迁移
        check(db.is_file(), "数据库文件已创建")
        check(store.conn.execute("PRAGMA user_version").fetchone()[0] == 1, "user_version = 1")

        # upsert 幂等
        rows = sample(5)
        store.upsert_items(rows)
        check(store.count() == 5, "首轮写入 5 条")
        store.upsert_items(rows)
        check(store.count() == 5, "重复写入行数不变（upsert）")

        # 改一条后覆盖
        changed = [dict(rows[0], title="改过的标题")]
        store.upsert_items(changed)
        got = store.get_item("demo:item0")
        check(got is not None and got["title"] == "改过的标题", "同 id 写入覆盖字段")

        # JSON 字段往返
        check(got["images"] == ["https://example.com/0a.jpg"], "images 解回数组")
        check(got["extra"] == {"src": "test"}, "extra 解回对象")
        check(got["stats"]["view"] == 1000, "stats 映射 view")

        # 排序：freshness 按发布时间倒序
        first, cur = store.page(limit=2)
        check([r["id"] for r in first] == ["demo:item0", "demo:item1"], "freshness 排序正确")
        check(cur is not None, "满页时给出 next_cursor")

        # 游标翻页不重不漏
        second, cur2 = store.page(limit=2, cursor=cur)
        check([r["id"] for r in second] == ["demo:item2", "demo:item3"], "第二页接着上一页")
        third, cur3 = store.page(limit=2, cursor=cur2)
        check([r["id"] for r in third] == ["demo:item4"], "最后一页只有 1 条")
        check(cur3 is None, "到底时 next_cursor 为 None")

        # engagement 排序
        eng, _ = store.page(sort="engagement", limit=5)
        check(len(eng) == 5, "engagement 排序可执行")

        # 过滤
        vids, _ = store.page(kind="video", limit=10)
        check(len(vids) == 3, "按 kind 过滤（5 条里 3 个 video）")
        none, _ = store.page(platforms=["nope"], limit=10)
        check(none == [], "不存在的平台返回空")

        # published_at 缺失沉底
        store.upsert_items([{"id": "demo:noTime", "platform": "demo", "kind": "list", "title": "无时间"}])
        tail, _ = store.page(limit=10)
        check(tail[-1]["id"] == "demo:noTime", "缺 time 的条目排在最后")

        # runs
        run_id = store.start_run("demo")
        store.finish_run(run_id, ok=True, count=5)
        runs = store.recent_runs(1)
        check(runs[0]["ok"] == 1 and runs[0]["count"] == 5, "runs 记录成功轮次")
        bad = store.start_run("broken")
        store.finish_run(bad, ok=False, count=0, error="timeout")
        check(store.recent_runs(1)[0]["error"] == "timeout", "runs 记录失败原因")

        # plugins
        store.upsert_plugin("demo", "0.1.0", sha256="abc", source="registry")
        store.set_enabled("demo", False)
        row = store.list_plugins()[0]
        check(row["enabled"] == 0 and row["version"] == "0.1.0", "插件禁用状态可写可读")
        store.delete_plugin("demo")
        check(store.list_plugins() == [], "插件可删除")

        # 游标编解码
        check(decode_cursor(encode_cursor({"published_at": 123, "id": "a:b"})) == (123, "a:b"),
              "游标编解码对称")
        check(decode_cursor("坏数据") is None, "非法游标返回 None")

        # 平台统计
        stats = {r["platform"]: r["count"] for r in store.platforms()}
        check(stats.get("demo") == 6, "平台统计条数")

        store.close()

    print(f"T29 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
