"""卡片 → 详情共享元素变形的静态回归。

真效果由 probes/check_card_morph.py 在真浏览器里验（需要服务在跑）；
这里守住几件容易被重构悄悄弄丢的事：
1. 卡片与详情页根部共用 of-card，浏览器才有几何插值的两个端点；
2. 0.7s / expo-out，两个方向都靠同一组 keyframes 收尾；
3. 返回时列表里那张卡片要先在场（feedCache + data-vt-item），否则没有落点；
4. 不支持 View Transition 或用户关了动效时直接跳，不硬上。
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
API = (SRC / "api.ts").read_text(encoding="utf-8")

CASES: list[tuple[str, callable]] = []


def case(fn):
    CASES.append((fn.__name__, fn))
    return fn


@case
def test_shared_element_css() -> None:
    for needle in (
        "html.nav-vt::view-transition-group(of-card)",
        "html.nav-vt::view-transition-old(of-card)",
        "html.nav-vt::view-transition-new(of-card)",
        "@keyframes nav-card-in",
        "0.42s",
        "cubic-bezier(0.16, 1, 0.3, 1)",
    ):
        assert needle in CSS, "theme.css 缺 " + needle
    # 几何交给浏览器插值，不能再写死缩放倍数
    assert "scale(1.075)" not in CSS, "of-card 还在写死放大倍数，共享元素变形会被覆盖"


@case
def test_blurry_snapshot_is_hidden() -> None:
    # 旧卡片快照是从卡片尺寸放大的位图，放大就是糊的：进场不画它，只留详情页那张
    assert "html.nav-vt::view-transition-old(of-card) {" in CSS
    assert "animation: none;\n  opacity: 0;" in CSS, "进场的旧卡片快照没被藏掉"
    # 返回方向相反：留详情页快照，藏卡片快照
    assert "html.nav-vt.nav-vt-back::view-transition-new(of-card)" in CSS
    assert "html.nav-vt.nav-vt-back::view-transition-old(of-card)" in CSS
    assert "nav-card-out" not in CSS, "nav-card-out 已废弃，旧快照不再做淡出"


@case
def test_old_page_fades_behind() -> None:
    for needle in (
        "html.nav-vt::view-transition-old(root)",
        "nav-root-out",
        "html.nav-vt::view-transition-new(root)",
    ):
        assert needle in CSS, "theme.css 缺 " + needle
    assert "of-page" not in CSS, "of-page 的旧规则还在，会和 of-card 抢同一页"


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
    ):
        assert needle in NAV_TS, "navTransition.ts 缺 " + needle
    assert "of-page" not in NAV_TS, "helper 还在给整页起名字"


@case
def test_app_waits_for_snapshot() -> None:
    # mode=wait 会让旧页先播 0.26s 退场，快照抓到的是旧 DOM
    assert 'AnimatePresence mode="wait"' not in APP, "路由还在用 mode=wait，View Transition 会抓错页"
    assert "as { vt?: boolean }" in APP, "没读 location.state.vt"
    assert "instant || reduce ? false" in APP, "走过渡的那一页还在播进场动画"


@case
def test_detail_shell_is_the_target() -> None:
    # 详情页一挂载就得有 of-card，否则新 DOM 里没有变形右端，只剩淡出
    assert "function Shell(" in ITEM, "详情页没有过渡载体"
    assert 'viewTransitionName: "of-card"' in ITEM, "载体没挂 of-card"
    assert ITEM.count("<Shell>") >= 3, "错误态 / 骨架 / 正文没有都包进载体"
    assert "fromId: item?.id" in ITEM, "返回没带上是哪张卡片"


@case
def test_feed_restores_card_before_morph() -> None:
    assert "data-vt-item=" in FEED, "列表项没有可供返回定位的标记"
    assert 'vtName={item.id === backId ? "of-card" : undefined}' in FEED, "返回目标卡片没挂 of-card"
    assert "scrollIntoView" in FEED, "返回时没把卡片滚回视野"
    assert "feedCache" in API, "api.ts 没有首屏缓存，返回瞬间列表是空的"


@case
def test_entry_points() -> None:
    assert "runNavTransition" in FEED, "信息流没走过渡"
    assert "el ?? null" in FEED, "卡片元素没交给过渡"
    assert "onOpen: (id: string, el: HTMLElement) => void" in CARD
    assert "e.currentTarget" in CARD, "点击没把卡片元素带出来"
    assert "vtName" in CARD, "卡片没接 of-card 这个名字"
    assert "const goBack = () =>" in ITEM, "返回没走过渡"
    assert "back: 1" in ITEM, "返回没标方向"


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
