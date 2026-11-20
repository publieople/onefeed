"""动效覆盖的静态守门（2026-11-19）。

用户的原话是「左侧栏和右侧栏的动画怎么又没了」——这类回归不是逻辑坏了，
而是改结构时把动画依赖的东西弄丢了，测也测不出来。这里把每条动效依赖的
那个东西钉住：进场用 keyframes（随挂载自动播，不依赖两帧时序）、收起用
transition、收尾靠 setTimeout 卸载而不是动画回调。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_presence_hook_does_not_rely_on_a_second_render():
    hook = read("web/src/motion/usePresence.ts")
    # 主线程一忙，两次 setState 会被合并成一帧：元素出生即终态，过渡没有起点。
    assert "mounted: open || keep" in hook
    assert "return { mounted:" in hook and "shown: open" in hook
    assert "setTimeout" in hook and "clearTimeout" in hook
    assert "framer-motion" not in hook
    assert "requestAnimationFrame(" not in hook


def test_left_rail_transitions_its_own_column_width():
    shell = read("web/src/layout/Shell.tsx")
    assert "data-shell-left={shell.left}" in shell
    assert "shell.left === \"full\" ? LEFT_W_FULL : LEFT_W_RAIL" in shell
    # flex item 的 min-width:auto = min-content（子元素自己撑）会把宽度撑住，没有起点
    assert "min-w-0" in shell
    # 换宽一步到位，不做宽度过渡：过渡期间卡片容器查询每帧重算，实测 240ms 长任务。
    # 现在由中间列 200ms 位移 + 淡入接住这次跳变。
    assert "shell-col" in shell
    css = read("web/src/theme.css")
    assert ".shell-col" in css
    col = css.split(".shell-col {")[1].split("}")[0]
    assert "transition: none" in col, "列宽又加回过渡了：卡片容器查询会逐帧重算"
    assert "content-settle-expand" in css and "content-settle-collapse" in css
    assert "content-settle-expand" in shell or "content-settle-collapse" in shell
    # 两层常驻、各自固定宽度：过渡期间展开层不会被重排成 64px 宽
    sidebar = read("web/src/agent/AgentSidebar.tsx")
    assert 'data-shell-layer="full"' in sidebar and 'data-shell-layer="rail"' in sidebar
    assert "w-[240px]" in sidebar and "w-16" in sidebar
    assert ".side-layer" in css and '[data-on="false"]' in css


def test_right_drawer_enters_with_keyframes_and_leaves_with_transition():
    shell = read("web/src/layout/Shell.tsx")
    assert 'data-shell-drawer="right"' in shell
    assert "drawer-in fixed bottom-0 right-0 top-[57px]" in shell
    assert 'drawer.shown ? "translate-x-0 opacity-100" : "translate-x-full opacity-0"' in shell
    # 抽屉盖在内容上，不挤内容宽度：让位那条路会让中间列掉到 900 以下
    assert "paddingRight" not in shell


def test_bottom_sheet_keeps_a_mounted_exit():
    surface = read("web/src/agent/AgentSurface.tsx")
    assert "sheet-in fixed bottom-0" in surface
    assert "translate-y-6 opacity-0" in surface
    assert "export function AgentSheet({ shown = true, named = true }" in surface
    assert "usePresence(mode === \"sheet\", 220)" in surface
    # 退场期间不能顺手把唤起器也塞回来，否则两层叠在一起
    assert 'mode === "closed" || !sheet.mounted' in surface


def test_bottom_veil_stays_under_the_two_side_columns():
    """底部渐隐是给内容卡片的，横跨视口会顺手把侧栏底部刷成灰的。

    用户看到的是「稍后再看 / 快捷键 / 设置 三行发灰、像禁用」，其实颜色 token
    没变（一直 text-muted #6b7280），是那条 fixed inset-x-0 的渐变盖在上面。
    两栏都是不透明纸色底，用 z 序把它挡回去，不要靠算列宽。
    """
    surface = read("web/src/agent/AgentSurface.tsx")
    # 唤起器的外层已经被夹在内容列里（left/right 用 --shell-*-w），渐隐只铺内容区
    assert "pointer-events-none fixed bottom-0 z-30" in surface
    assert "left: \"var(--shell-left-w, 0px)\"" in surface
    assert "pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-paper" in surface

    shell = read("web/src/layout/Shell.tsx")
    assert "sticky top-[57px] z-40 h-[calc(100vh-57px)] min-w-0 shrink-0 overflow-hidden border-r border-line bg-paper" in shell
    assert "rail-in sticky top-[57px] z-40 h-[calc(100vh-57px)] min-h-[420px] w-[320px] shrink-0 border-l border-line" in shell


def test_keyframes_and_reduce_motion_are_declared():
    css = read("web/src/theme.css")
    for name in ("sheet-in", "drawer-in", "rail-in"):
        assert "@keyframes " + name in css
        assert "." + name + " {" in css
    assert "animation: sheet-in 0.22s cubic-bezier(0.16, 1, 0.3, 1) backwards" in css
    # backwards：动画结束后不留 fill，收起时 transition 才抢得到 transform
    assert "backwards" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert '[data-shell-drawer="right"],' in css


def test_every_surface_that_pops_in_has_a_feedback():
    assert "motion.div" in read("web/src/components/ui/Confirm.tsx")
    assert "initial={{ opacity: 0, y: 10, scale: 0.985 }}" in read("web/src/components/ShortcutHelp.tsx")
    assert "initial={{ opacity: 0, y: -6, scale: 0.98 }}" in read("web/src/components/ui/ColsPicker.tsx")
    assert 'key={tab}' in read("web/src/components/RightRail.tsx")
    assert "rise fixed bottom-6 left-1/2 z-50" in read("web/src/pages/MarketPage.tsx")
    # 详情页两个 tab 的内容各自淡入，切 tab 不是硬换
    item = read("web/src/pages/ItemPage.tsx")
    assert '<div key="summary" className="rise">' in item
    assert '<div key="source" className="rise">' in item
    # Agent 轨迹每来一步都淡入
    assert 'className="fade-in flex items-start gap-1.5' in read("web/src/components/AgentConsole.tsx")
    # 收藏星标按下有回弹
    assert "active:scale-90" in read("web/src/agent/AgentThread.tsx")


def test_feed_status_and_saved_removal_are_animated():
    feed = read("web/src/pages/FeedPage.tsx")
    assert 'key={feed.moreLoading ? "loading" : "idle"}' in feed
    saved = read("web/src/components/SavedList.tsx")
    assert "leaving" in saved and "pointer-events-none -translate-x-1 opacity-0" in saved
    assert "setTimeout" in saved
    top = read("web/src/components/ScrollTop.tsx")
    assert "scale-100 opacity-100" in top and "scale-90 opacity-0" in top
    assert "rise" in read("web/src/agent/AgentHistory.tsx")

def test_sidebars_ease_wheel_scrolling():
    """侧栏滚轮缓动（2026-11-20）。

    用户报「左右侧边栏仍然没有平滑滚动」。Windows 的 Chrome 滚轮是一次跳一整段，
    CSS 的 scroll-behavior 只管键盘和程序化滚动。这里钉住三件事：
    ① 六个侧栏列表都挂了标记；② 缓动只在 document 捕获阶段接管带标记的容器；
    ③ 每帧写位置必须 behavior:"instant"，否则容器上的 smooth 会把赋值变成
    浏览器自己的动画，缓动变成抢方向盘（实测每帧只挪 2px）。
    """
    hook = read("web/src/motion/useSmoothWheelScroll.ts")
    assert "data-smooth-scroll" in hook
    assert "passive: false" in hook and "capture: true" in hook
    assert "prefers-reduced-motion" in hook
    assert 'behavior: "instant"' in hook
    # 到边交回外层：不能把滚轮一路吞掉，否则贴边时页面完全动不了
    assert "box.scrollTop <= 0 && delta < 0" in hook
    assert "box.scrollTop >= max - 1 && delta > 0" in hook

    app = read("web/src/App.tsx")
    assert "useSmoothWheelScroll()" in app

    for rel in (
        "web/src/agent/AgentSidebar.tsx",
        "web/src/agent/AgentThread.tsx",
        "web/src/components/SavedList.tsx",
        "web/src/components/SummaryList.tsx",
        "web/src/components/FavoritesList.tsx",
        "web/src/components/RightRail.tsx",
    ):
        assert "data-smooth-scroll" in read(rel), rel + " 的滚动容器没挂缓动标记"

    css = read("web/src/theme.css")
    assert "[data-smooth-scroll] {" in css
    assert "scroll-behavior: smooth" in css.split("[data-smooth-scroll] {")[1].split("}")[0]
