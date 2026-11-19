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
    assert "width: shell.left === \"full\" ? LEFT_W_FULL : LEFT_W_RAIL" in shell
    # flex item 的 min-width:auto = min-content（子元素固定 288）会把宽度撑住，没有起点
    assert "min-w-0" in shell
    assert "transition-[width] duration-[220ms] ease-out" in shell


def test_right_drawer_enters_with_keyframes_and_leaves_with_transition():
    shell = read("web/src/layout/Shell.tsx")
    assert 'data-shell-drawer="right"' in shell
    assert "drawer-in fixed inset-y-0 right-0" in shell
    assert 'drawer.shown ? "translate-x-0 opacity-100" : "translate-x-full opacity-0"' in shell
    # 右抽屉开着的时候内容列要让位，收起后这段 padding 也要过渡回去，不能瞬间一跳
    assert "transition-[padding-right] duration-[240ms] ease-out" in shell


def test_bottom_sheet_keeps_a_mounted_exit():
    surface = read("web/src/agent/AgentSurface.tsx")
    assert "sheet-in fixed inset-x-0 bottom-0" in surface
    assert "translate-y-6 opacity-0" in surface
    assert "export function AgentSheet({ shown = true, named = true }" in surface
    assert "usePresence(mode === \"sheet\", 220)" in surface
    # 退场期间不能顺手把唤起器也塞回来，否则两层叠在一起
    assert 'mode === "closed" || !sheet.mounted' in surface


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
