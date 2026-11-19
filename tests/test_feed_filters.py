"""筛选条件进出详情页的静态回归。

真效果由 probes/check_feed_filters.py 在真浏览器里验（需要服务在跑）；
这里守住四件容易被重构弄丢的事：
1. 筛选条件是 URL 的一部分（刷新 / 分享 / 返回都认得），不是组件里的临时 state；
2. 返回时列表里那张卡片在场并滚回视野，否则共享元素变形没有落点；
3. 走共享元素变形的那次跳转，滚动由跳转自己决定，App 的切页 scrollTo 要让位；
4. 分段控件把选中态暴露成 aria-pressed，胶囊与分段控件的状态可被断言。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "src"
FEED = (SRC / "pages" / "FeedPage.tsx").read_text(encoding="utf-8")
APP = (SRC / "App.tsx").read_text(encoding="utf-8")
API = (SRC / "api.ts").read_text(encoding="utf-8")
CHIPS = (SRC / "components" / "Chips.tsx").read_text(encoding="utf-8")
RAIL = (SRC / "components" / "ui" / "TabRail.tsx").read_text(encoding="utf-8")

CASES: list[tuple[str, callable]] = []


def case(fn):
    CASES.append((fn.__name__, fn))
    return fn


@case
def test_filters_live_in_url() -> None:
    assert "useSearchParams" in FEED, "FeedPage 不再从 URL 读筛选条件"
    for needle in ('params.get("p")', 'params.get("q")', 'params.get("sort")', 'params.get("range")'):
        assert needle in FEED, "FeedPage 缺 " + needle
    # 改筛选写回 URL，且不堆历史记录（否则返回要按很多次）
    assert 'sp.set("p"' in FEED and 'sp.delete("p")' in FEED
    assert 'sp.set("q"' in FEED and 'sp.delete("q")' in FEED
    assert 'sp.set("sort"' in FEED and 'sp.delete("sort")' in FEED
    assert 'sp.set("range", "today")' in FEED and 'sp.delete("range")' in FEED
    assert "setParams(sp, { replace: true })" in FEED, "筛选写 URL 用了 push，返回会变成逐条回退"


@case
def test_return_keeps_context() -> None:
    # 进详情时把当前地址与卡片 id 带过去
    assert "from: location.pathname + location.search" in FEED, "进详情没带返回地址"
    assert "fromId: id" in FEED, "进详情没带卡片 id，返回时没有落点"
    # 还要把这条卡片的快照带过去，详情首屏才有共享元素（冷卡片也能有转场）
    assert "item: seed" in FEED, "进详情没带卡片快照，冷卡片转场会退化成整页淡出"
    assert "fromId: id, item: seed" in FEED
    # 返回后按 id 找卡片并滚回视野
    assert 'data-vt-item="' in FEED and "scrollIntoView" in FEED
    assert "block: \"center\"" in FEED or 'block: "center"' in FEED


@case
def test_scroll_owner_is_nav_transition() -> None:
    # 进详情：在快照前滚到顶，详情页不会从列表的滚动位置开始
    assert "window.scrollTo({ top: 0, behavior: \"auto\" })" in FEED
    # App 的切页滚动必须让位给 vt 跳转，否则返回时把落点冲掉
    assert "location.state as { vt?: boolean } | null)?.vt) return;" in APP
    assert "window.scrollTo({ top: 0, behavior: \"auto\" })" in APP


@case
def test_feed_cache_seeds_first_paint() -> None:
    assert "const feedCache = new Map<string, FeedResponse>()" in API, "feedCache 没了，返回首帧列表为空、变形没有落点"
    assert "cacheKey" in API and "feedCache.get" in API
    assert "feedCache.set(cacheKey" in API


@case
def test_segmented_control_exposes_pressed() -> None:
    assert 'aria-pressed={on}' in FEED, "分段控件没暴露 aria-pressed"
    assert "aria-pressed={isOn(item)}" in RAIL, "平台胶囊没暴露 aria-pressed"
    assert "onChange: (ids: string[]) => void;" in CHIPS, "Chips 的多选结果没有交回 FeedPage"


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {name}: {exc}")
    print(f"{len(CASES) - failed}/{len(CASES)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
