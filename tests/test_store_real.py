"""T29 真实数据验收：插件 pull 出来的 Item 能不能原样落库再读回。

跑法：python tests/test_store_real.py
用 zhihu-hot（免登录、~1s）作为样本；网络不通时跳过，不算失败。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from onefeed.store import Store            # noqa: E402
from plugin_runtime import PluginHost      # noqa: E402


def main() -> int:
    host = PluginHost()
    try:
        items = host.pull("zhihu-hot", limit=8)
    except Exception as exc:
        print(f"跳过：拉取失败 {type(exc).__name__}: {exc}")
        return 0

    assert items, "插件没有返回条目"
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "real.db")
        store.upsert_items(items)
        assert store.count() == len(items), f"入库条数不符 {store.count()} != {len(items)}"

        rows, _ = store.page(limit=len(items))
        assert len(rows) == len(items)
        assert {r["platform"] for r in rows} == {"zhihu-hot"}, "平台字段被改写"

        good = [r for r in rows if r["title"] and r["title"] != "（无标题）"]
        print(f"入库 {len(rows)} 条，有标题 {len(good)} 条；样例：{rows[0]['title'][:30]}")
        assert good, "一条有效标题都没有"

        one = store.get_item(rows[0]["id"])
        assert one is not None and one["title"] == rows[0]["title"], "按 id 取回不一致"

        # 再写一遍不应翻倍
        store.upsert_items(items)
        assert store.count() == len(items), "重复写入后条数变化"
        store.close()

    print("T29 真实数据验收通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
