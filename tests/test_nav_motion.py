"""卡片 → 详情缩放动效的静态回归。

真效果由 probes/check_card_morph.py 在真浏览器里验（需要服务在跑）；
这里守住几件容易被重构悄悄弄丢的事：
1. 跳页包了 View Transition，且主题那套全局规则不会串到导航上；
2. 卡片单独成组（of-card），0.7s / expo-out，返回退场的是整页（of-page）；
3. 不支持 View Transition 或用户关了动效时直接跳，不硬上。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "src"
CSS = (SRC / "theme.css").read_text(encoding="utf-8")
NAV_TS = (SRC / "navTransition.ts").read_text(encoding="utf-8")
APP = (SRC / "App.tsx").read_text(encoding="utf-8")
FEED = (SRC / "pages" / "FeedPage.tsx").read_text(encoding="utf-8")
ITEM = (SRC / "pages" / "ItemPage.tsx").read_text(encoding="utf-8")
CARD = (SRC / "components" / "Card.tsx").read_text(encoding="utf-8")

CASES: list[tuple[str, callable]] = []


def case(fn):
    CASES.append((fn.__name__, fn))
    return fn


@case
def test_card_group_css() -> None:
    for needle in (
        "html.nav-vt::view-transition-group(of-card)",
        "html.nav-vt::view-transition-old(of-card)",
        "@keyframes nav-card-lift",
        "scale(1.075)",
        "0.7s",
        "cubic-bezier(0.16, 1, 0.3, 1)",
    ):
        assert needle in CSS, "theme.css 缺 " + needle


@case
def test_back_transition_css() -> None:
    for needle in (
        "html.nav-vt::view-transition-old(of-page)",
        "@keyframes nav-page-down",
        "scale(0.972)",
        "html.nav-vt::view-transition-old(root)",
    ):
        assert needle in CSS, "theme.css 缺 " + needle


@case
def test_nav_suppression_and_scoping() -> None:
    assert ".nav-vt," in CSS, "缺 nav-vt 抑制规则"
    assert "transition: none !important" in CSS, "nav-vt 没有关掉逐元素过渡"
    # 换肤的 reveal polygon 只认 theme-vt，不能串到跳页上
    assert "html.theme-vt::view-transition-new(root)" in CSS
    assert "html.theme-vt.dark::view-transition-new(root)" in CSS
    assert "\n.dark::view-transition-new(root)" not in CSS


@case
def test_helper_fallbacks() -> None:
    for needle in (
        "export function runNavTransition",
        "startViewTransition",
        "prefers-reduced-motion",
        "flushSync",
        "viewTransitionName",
        "of-card",
        "of-page",
    ):
        assert needle in NAV_TS, "navTransition.ts 缺 " + needle


@case
def test_app_waits_for_snapshot() -> None:
    # mode=wait 会让旧页先播 0.26s 退场，快照抓到的是旧 DOM
    assert 'AnimatePresence mode="wait"' not in APP, "路由还在用 mode=wait，View Transition 会抓错页"
    assert "as { vt?: boolean }" in APP, "没读 location.state.vt"
    assert "instant || reduce ? false" in APP, "走过渡的那一页还在播进场动画"


@case
def test_entry_points() -> None:
    assert "runNavTransition" in FEED, "信息流没走过渡"
    assert "el ?? null" in FEED, "卡片元素没交给过渡"
    assert "onOpen: (id: string, el: HTMLElement) => void" in CARD
    assert "e.currentTarget" in CARD, "点击没把卡片元素带出来"
    assert "const goBack = () => runNavTransition" in ITEM, "返回没走过渡"
    assert 'state: { vt: true, back: 1 }' in ITEM, "返回没标方向"


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print("  PASS", name)
        except AssertionError as exc:
            failed += 1
            print("  FAIL", name, exc)
    print(f"test_nav_motion: {len(CASES) - failed}/{len(CASES)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
