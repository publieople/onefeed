"""静态演示站快照（012-demo-site）的验收：快照必须是干净的只读数据。

跑法：
    uv run python tests/test_demo_snapshot.py

不联网、不开浏览器：只把 fixtures 走一遍导出，再看产物。
守的是三条底线：不泄漏本机路径与密钥、不留 http:// 混合内容、字段形状够前端用。
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
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

VERBOSE = "--verbose" in sys.argv
CHECKS = 0

_spec = importlib.util.spec_from_file_location("export_demo", ROOT / "scripts" / "export_demo.py")
if _spec is None or _spec.loader is None:  # pragma: no cover - 路径写死，坏了就是仓库结构变了
    raise SystemExit("找不到 scripts/export_demo.py")
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)


def check(cond: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(label)
    if VERBOSE:
        print(f"  ok  {label}")


def load_snapshot() -> tuple[dict, str, int]:
    # 临时目录自己收干净：某些环境下 TMPDIR 指向仓库根，跑一次测试就会留一个空目录
    tmp = Path(tempfile.mkdtemp(prefix="onefeed-test-demo-"))
    out = tmp / "demo" / "api.json"
    try:
        home, demo = os.environ.get("ONEFEED_HOME"), os.environ.get("ONEFEED_DEMO")
        snap = export.build(out)
        check(os.environ.get("ONEFEED_HOME") == home, "导出后要把 ONEFEED_HOME 还原")
        check(os.environ.get("ONEFEED_DEMO") == demo, "导出后要把 ONEFEED_DEMO 还原")
        text = out.read_text(encoding="utf-8")
        check(json.loads(text) == snap, "返回值与落盘内容一致")
        return snap, text, out.stat().st_size
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_shape(snap: dict, text: str) -> None:
    for key in ("meta", "health", "summary", "settings", "feed"):
        check(key in snap, f"快照要有 {key}")
    meta, health, feed = snap["meta"], snap["health"], snap["feed"]
    check(meta["items"] >= 30, f"条目太少（{meta['items']}）")
    check(len(meta["platforms"]) >= 5, f"平台太少（{meta['platforms']}）")
    check(meta["newest_published_at"] > 0, "要记下最新一条的时间，演示站的「今天」靠它")
    check(health.get("demo") is True, "health.demo 必须是 true，前端靠它换提示条")
    check(feed.get("next") is None, "静态站没有下一页")
    check(feed.get("parsed") is None, "静态站没有解析时间")
    check(len(feed["items"]) == feed["count"], "count 要等于实际条目数")


def test_clean(snap: dict, text: str) -> None:
    health, settings = snap["health"], snap["settings"]
    check(health.get("db") == "", "health.db 不能带出本机路径")
    resolved = settings.get("resolved") or {}
    check(resolved.get("state_dir") == "", "state_dir 要抹掉")
    check(resolved.get("plugins_dir") == "", "plugins_dir 要抹掉")
    values = settings.get("settings") or {}
    for key, value in values.items():
        if key.endswith("_key") or key.endswith("_token"):
            check(value == "", f"settings.{key} 不能出快照")
    for provider in values.get("ai_providers") or []:
        if isinstance(provider, dict):
            check(provider.get("api_key") in (None, ""), "ai_providers[].api_key 不能出快照")
    for pattern in export.SECRET_PATTERNS:
        check(pattern.search(text) is None, f"快照里还有密钥：{pattern.pattern}")
    check("http://" not in text, "不能留 http://，Pages 是 https 会拦混合内容")
    check("/Users/" not in text and "\\\\Users\\\\" not in text, "不能带本机用户目录")


def test_feed(snap: dict) -> None:
    items = snap["feed"]["items"]
    ids = [str(item.get("id") or "") for item in items]
    check(all(ids), "每条都要有 id")
    check(len(set(ids)) == len(ids), "id 不能重复")
    for item in items:
        label = str(item.get("id"))
        check(isinstance(item.get("title"), str) and item["title"].strip() != "", f"{label} 要有标题")
        check(isinstance(item.get("platform"), str) and item["platform"], f"{label} 要有平台")
        check(isinstance(item.get("like_count"), int), f"{label} 的 like_count 要是数字（前端字段名）")
        cover = item.get("cover")
        if cover:
            check(str(cover).startswith("https://"), f"{label} 的封面要走 https")
    # 宿主默认是「平台轮流混排」，全局不严格有序；但每个平台内部要是新鲜度降序
    by_platform: dict[str, list[int]] = {}
    for item in items:
        key = int(item.get("published_at") or 0) or int(item.get("fetched_at") or 0)
        by_platform.setdefault(str(item["platform"]), []).append(key)
    for platform, keys in by_platform.items():
        check(keys == sorted(keys, reverse=True), f"{platform} 内部要按新鲜度降序（published_at 空时退回 fetched_at）")
    check(snap["summary"].get("offline") is True, "summary.offline 要是 true")


def test_platform_counts(snap: dict) -> None:
    rows = snap["health"].get("platforms") or []
    total = sum(int(row.get("count") or 0) for row in rows)
    check(rows, "health.platforms 不能空")
    check(total == len(snap["feed"]["items"]), f"分平台计数之和 {total} 与条目数不符")


def main() -> int:
    snap, text, size = load_snapshot()
    tests = [
        lambda: test_shape(snap, text),
        lambda: test_clean(snap, text),
        lambda: test_feed(snap),
        lambda: test_platform_counts(snap),
    ]
    for fn in tests:
        fn()
    check(size < 3 * 1024 * 1024, f"快照太大：{size / 1024:.0f} KB")
    print(f"✅ 演示站快照 {snap['meta']['items']} 条 / {len(snap['meta']['platforms'])} 个平台 / {size / 1024:.0f} KB / {CHECKS} 项通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
