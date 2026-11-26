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

from onefeed.store import SCHEMA_VERSION, Store, decode_cursor, encode_cursor  # noqa: E402

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
    # Windows 上 sqlite 句柄偶尔比 close_all 晚一步释放，清理失败不该让检查挂掉
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db = Path(tmp) / "test.db"
        store = Store(db)

        # 建表与迁移
        check(db.is_file(), "数据库文件已创建")
        check(store.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION, "user_version = SCHEMA_VERSION")
        # v5：Agent 运行、步骤、收藏标记都在同一库；hidden 默认不进 feed
        check(store.get_mark("demo:item0")["saved"] is False, "v5 item_marks 默认未收藏")

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

        # engagement 排序：同平台内按分位归一，不拿别人的百万点赞压死小平台
        eng, _ = store.page(sort="engagement", limit=5)
        check(len(eng) == 5, "engagement 排序可执行")
        check(eng[0]["id"] == "demo:item4", "互动最高的排第一（item4）")
        check(eng[0]["engage_score"] == 1000, "本平台第一名记满分 1000")
        check(eng[0]["engage_score"] > store.get_item("demo:item0")["engage_score"], "同平台内高处分数更高")

        # 跨平台：另一个平台只有个位数互动，它的头名也应当是 1000，而不是被 demo 压成 0
        store.upsert_items([
            {"id": "tiny:a", "platform": "tiny", "kind": "short", "title": "小平台第一",
             "like": 9, "published_at": 1000},
            {"id": "tiny:b", "platform": "tiny", "kind": "short", "title": "小平台第二",
             "like": 1, "published_at": 999},
        ])
        check(store.get_item("tiny:a")["engage_score"] == 1000, "小平台头名同样是 1000")
        check(store.get_item("tiny:b")["engage_score"] == 0, "小平台末名是 0")
        mix, _ = store.page(sort="engagement", limit=2)
        check({r["platform"] for r in mix} == {"demo", "tiny"}, "跨平台热度不再被大计数平台垄断")
        # 没有互动字段的平台整体记 0，不许并列满分
        store.upsert_items([{"id": "flat:a", "platform": "flat", "kind": "short", "title": "无互动"}])
        check(store.get_item("flat:a")["engage_score"] == 0, "整平台无互动时记 0")

        # 过滤
        vids, _ = store.page(kind="video", limit=10)
        check(len(vids) == 3, "按 kind 过滤（5 条里 3 个 video）")
        none, _ = store.page(platforms=["nope"], limit=10)
        check(none == [], "不存在的平台返回空")

        # published_at 缺失：排序退回采集时间，但字段本身仍是 0（显示层不编时间）。
        # 以前这里减 86400，刚抓到的无时间条目会被当成"一天前"，刷新后永远上不了首屏。
        store.upsert_items([{"id": "demo:noTime", "platform": "demo", "kind": "list", "title": "无时间"}])
        page_all, _ = store.page(limit=10)
        no_time = next(r for r in page_all if r["id"] == "demo:noTime")
        check(no_time["published_at"] == 0, "缺 time 的条目 published_at 保持 0")
        check(any(r["id"] == "demo:noTime" for r in page_all), "缺 time 的条目不会被丢")
        demo_rows = [r for r in page_all if r["platform"] == "demo"]
        check(demo_rows[0]["id"] == "demo:noTime", "缺 time 的条目按采集时间排在本平台最前，刚抓的不会沉底")

        # 无发布时间条目的游标必须与 SQL 的排序键一致：以前游标减了 86400，
        # 第一页之后的条目全部落在游标下方，翻页直接到底。
        store.upsert_items([
            {"id": "nt:a", "platform": "nt", "kind": "list", "title": "无时间 A",
             "fetched_at": 1000},
            {"id": "nt:b", "platform": "nt", "kind": "list", "title": "无时间 B",
             "fetched_at": 2000},
            {"id": "nt:c", "platform": "nt", "kind": "list", "title": "无时间 C",
             "fetched_at": 3000},
        ])
        nt_first, nt_cur = store.page(platforms=["nt"], limit=1)
        nt_second, nt_cur2 = store.page(platforms=["nt"], limit=1, cursor=nt_cur)
        nt_third, nt_cur3 = store.page(platforms=["nt"], limit=1, cursor=nt_cur2)
        check([r["id"] for r in nt_first + nt_second + nt_third] == ["nt:c", "nt:b", "nt:a"],
              "无发布时间条目按采集时间翻页不重不漏")
        check(nt_cur3 is None, "无发布时间条目翻到最后一页时结束")

        # 关键词里的 % / _ 是 LIKE 通配符，必须当字面量搜；以前搜 "%" 会把整库都捞出来
        store.upsert_items([
            {"id": "kw:pct", "platform": "kw", "kind": "list", "title": "限时 100% 返现"},
            {"id": "kw:under", "platform": "kw", "kind": "list", "title": "a_b 命名规范"},
            {"id": "kw:plain", "platform": "kw", "kind": "list", "title": "普通条目"},
        ])
        pct, _ = store.page(platforms=["kw"], keyword="%", limit=10)
        check([r["id"] for r in pct] == ["kw:pct"], "搜 % 只命中标题里真有 % 的条目")
        under, _ = store.page(platforms=["kw"], keyword="_", limit=10)
        check([r["id"] for r in under] == ["kw:under"], "搜 _ 只命中标题里真有下划线的条目")
        literal, _ = store.page(platforms=["kw"], keyword="100%", limit=10)
        check([r["id"] for r in literal] == ["kw:pct"], "带 % 的完整关键词仍按字面量搜到")

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

        # details：详情页缓存按 item_id 存，过期视为没有
        store.save_detail("demo:item0", {"body": {"kind": "text", "value": "正文"}})
        cached = store.get_detail("demo:item0", max_age=3600)
        check(cached is not None and cached["payload"]["body"]["value"] == "正文", "详情可写可读")
        store.conn.execute("UPDATE details SET fetched_at = fetched_at - 7200 WHERE item_id = ?", ("demo:item0",))
        check(store.get_detail("demo:item0", max_age=3600) is None, "过期详情视为没有")
        check(store.get_detail("demo:item0", max_age=0) is not None, "不设 TTL 时能读到旧缓存")
        store.drop_detail("demo:item0")
        check(store.get_detail("demo:item0", max_age=0) is None, "详情可删除")

        # 游标编解码
        check(decode_cursor(encode_cursor({"published_at": 123, "id": "a:b"})) == (123, "a:b"),
              "游标编解码对称")
        check(decode_cursor("坏数据") is None, "非法游标返回 None")

        # 平台统计
        stats = {r["platform"]: r["count"] for r in store.platforms()}
        check(stats.get("demo") == 6, "平台统计条数")

        store.close_all()
        # Windows 上偶尔还有句柄没释放，删不掉就重试几次（不影响检查结果）
        for leftover in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
            for _ in range(10):
                try:
                    leftover.unlink(missing_ok=True)
                    break
                except PermissionError:
                    time.sleep(0.2)

    print(f"T29 通过：{CHECKS} 项检查")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())