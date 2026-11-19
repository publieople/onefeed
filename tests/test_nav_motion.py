"""卡片 → 详情共享元素转场的静态回归（of-media / of-title 版）。

真效果靠真浏览器验（本机 headless 的 visibilityState 是 hidden，View Transition 会被跳过，
所以这里守的是「结构上还成不成立」）：
1. 卡片与详情页各有一个媒体框、一个标题，两个固定名字 of-media / of-title；
2. 0.42s + expo-out，只让目标侧快照参与插值；
3. 名称最多三个、并发第二次直接瞬切（上一次 cleanup 不能清掉这一次的名字）；
4. 顶栏独立成层不参与整页动画；转场期间锁滚动，不锁会让冻结快照与新页错位；
5. 返回时列表里那张卡片先在场（feedCache + data-vt-item + 重锚），否则没有落点；
6. 不支持 View Transition 或用户关了动效时直接跳，不硬上。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "src"
CSS = (SRC / "theme.css").read_text(encoding="utf-8")
NAV = (SRC / "motion" / "nav.ts").read_text(encoding="utf-8")
TOKENS = (SRC / "motion" / "tokens.ts").read_text(encoding="utf-8")
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
        "html.nav-vt::view-transition-group(of-media)",
        "html.nav-vt::view-transition-group(of-title)",
        "html.nav-vt::view-transition-old(of-media)",
        "html.nav-vt::view-transition-new(of-media)",
        "html.nav-vt.nav-vt-back::view-transition-old(of-media)",
        "@keyframes nav-el-in",
        "0.42s",
        "cubic-bezier(0.16, 1, 0.3, 1)",
    ):
        assert needle in CSS, "theme.css 缺 " + needle
    # 旧名字必须清干净：两套规则同时存在会抢同一块区域
    assert "of-card" not in CSS, "theme.css 里还留着 of-card"
    # 几何交给浏览器插值，不能写死缩放
    assert "scale(1.075)" not in CSS, "还在写死放大倍数，共享元素变形会被覆盖"


@case
def test_only_target_snapshot_is_painted() -> None:
    # 推入方向藏旧侧（卡片小图放大就是糊的），返回方向反过来
    assert "html.nav-vt::view-transition-old(of-media)" in CSS
    assert "html.nav-vt.nav-vt-back::view-transition-new(of-media)" in CSS
    assert "nav-card-out" not in CSS, "nav-card-out 已废弃"


@case
def test_topbar_is_its_own_layer() -> None:
    assert "html.nav-vt::view-transition-group(of-topbar)" in CSS
    assert "animation: none;" in CSS.split("of-topbar")[1][:200]
    assert 'viewTransitionName: "of-topbar"' in (SRC / "components" / "TopBar.tsx").read_text(encoding="utf-8")


@case
def test_scroll_lock_and_suppression() -> None:
    assert "html.vt-running" in CSS, "缺转场期滚动锁"
    assert "scrollbar-gutter: stable" in CSS, "锁滚动没保住滚动条宽度，内容会横跳"
    assert ".nav-vt," in CSS
    assert "transition: none !important" in CSS


@case
def test_nav_primitives() -> None:
    for needle in (
        "export function runNav",
        "startViewTransition",
        "prefers-reduced-motion",
        "flushSync",
        "viewTransitionName",
        "clearStrayNames",
        "inflight",
        "MAX_NAMES",
    ):
        assert needle in NAV, "motion/nav.ts 缺 " + needle
    # 并发保护：上一次没跑完就瞬切，不能让两次 cleanup 互相清名字
    assert "inflight" in NAV and "if (inflight)" in NAV
    assert "of-page" not in NAV, "helper 还在给整页起名字"
    # 名字上限：超过三个就不该再飞（多飞一层会多出一张糊图）
    assert "slice(0, MAX_NAMES)" in NAV or "MAX_NAMES" in NAV


@case
def test_tokens_are_the_only_source() -> None:
    assert "export const DUR" in TOKENS and "export const EASE" in TOKENS
    legacy = (SRC / "motion.ts").read_text(encoding="utf-8")
    assert 'from "./motion/tokens"' in legacy, "老的 ../motion 引用没有转成 re-export"


@case
def test_app_routes_without_wait_animation() -> None:
    assert 'AnimatePresence mode="wait"' not in APP, "路由还在用 mode=wait，View Transition 会抓错页"
    assert "state.vt" in APP or "vt" in APP
    assert "instant" in APP, "没区分「有没有走过渡」"


@case
def test_card_is_a_link_and_owns_the_names() -> None:
    assert "motion.a" in CARD and 'href={"/item/" + encodeURIComponent(item.id)}' in CARD
    assert "e.button !== 0" in CARD, "没把中键 / ⌘点击交还给浏览器"
    assert "e.preventDefault()" in CARD
    assert 'data-vt="media"' in CARD and 'data-vt="title"' in CARD
    assert "vtNames" in CARD
    assert "role=\"button\"" not in CARD, "卡片还是 button 语义，新标签页打不开"


@case
def test_feed_hands_over_two_names() -> None:
    assert "data-vt-item=" in FEED
    assert "restoreAnchor" in FEED, "返回时没有重锚（图片加载完卡片会移位）"
    assert '"of-media"' in FEED and '"of-title"' in FEED
    assert 'data-vt="media"' in FEED, "没从被点卡片上取媒体框"
    assert "feedCache" in API, "api.ts 没有首屏缓存，返回瞬间列表是空的"


@case
def test_item_keeps_media_above_tabs() -> None:
    # 媒体区提到 tab 之上常驻：以前切 tab 会卸载播放器，进度归零
    assert 'data-vt="media"' in ITEM and 'viewTransitionName: "of-media"' in ITEM
    assert 'data-vt="title"' in ITEM and 'viewTransitionName: "of-title"' in ITEM
    assert "showHero" in ITEM, "详情页没有 hero 判定"
    assert "runNav(" in ITEM and '"back"' in ITEM, "返回没走过渡"
    assert "peekItem" in ITEM, "进详情没用预取垫底，首屏会闪骨架"


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
