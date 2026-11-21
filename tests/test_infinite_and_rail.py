"""左栏收放、底部唤起器、无限预取的静态守门。

这一轮改的三件事都在真机上出过问题：
  - 窄屏点「展开」变成 fixed 全屏浮层，盖住整页（沉浸感没了，还关不掉）；
  - 底部胶囊一直贴着底边，内容永远被压住一截；
  - 刷到底才开始取下一页，中途是一片空白，或者一冲就冲出内容。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_left_rail_expands_in_place_instead_of_covering_the_page():
    hook = read("web/src/layout/useShell.ts")
    shell = read("web/src/layout/Shell.tsx")
    # 浮层那套机制整体删掉：state / 全屏遮罩 / Esc 作用域都不该再出现
    assert "leftDrawer" not in hook and "leftDrawer" not in shell
    assert "setLeftDrawer" not in shell
    assert 'export type LeftLayout = "full" | "rail" | "hidden";' in hook
    assert 'width >= LEFT_RAIL ? (expanded ? "full" : "rail") : "hidden"' in hook
    # 图标轨上点展开 = 同一列变宽（走同一个 toggle），不是开一层盖住页面的东西
    assert "<AgentSidebar collapsed onExpand={shell.toggleLeft}" in shell
    collapsed = read("web/src/agent/AgentSidebar.tsx")
    assert "drawer" not in collapsed, "侧栏只剩钉住/图标轨两种形态"


def test_launcher_hides_on_scroll_down_and_returns_on_scroll_up():
    reveal = read("web/src/motion/useLauncherReveal.ts")
    assert "HIDE_AFTER" in reveal and "SHOW_ON_UP" in reveal and "EDGE" in reveal
    assert 'window.addEventListener("scroll"' in reveal
    assert "clientY >= window.innerHeight - EDGE" in reveal, "指针贴到底边也该让它出来"
    surface = read("web/src/agent/AgentSurface.tsx")
    assert "useLauncherReveal()" in surface
    assert "translate-y-[130%] opacity-0" in surface
    # 收起时不只是透明：点击与 Tab 都要够不到
    assert "tabIndex={shown ? 0 : -1}" in surface
    assert 'const reach = shown ? "pointer-events-auto" : "pointer-events-none";' in surface
    assert "data-agent-launcher-wrap" in surface


def test_scroll_top_button_appears_after_more_than_a_screen():
    src = read("web/src/components/ScrollTop.tsx")
    assert "SHOW_AFTER = 1.2" in src
    assert 'window.scrollTo({ top: 0, behavior: "smooth" })' in src
    assert "回到顶部" in src
    assert "<ScrollTop />" in read("web/src/App.tsx")


def test_feed_prefetches_the_next_page_before_reaching_the_bottom():
    feed = read("web/src/pages/FeedPage.tsx")
    api = read("web/src/api.ts")
    assert "new IntersectionObserver" in feed
    assert 'rootMargin: "0px 0px 1200px 0px"' in feed, "提前一屏半就要开始取"
    assert "正在获取新内容…" in feed
    assert "min-h-[56px]" in feed, "状态条高度固定，切换文案时页面不抖"
    assert "moreLoading" in api, "下一页要有独立状态，不能复用首屏 loading"
    assert "if (flight.current) return;" in api, "同一次翻页单飞，传感器会重复触发"
    assert "seen.has(entry.id)" in api, "追加要按 id 去重，重复 key 会直接报错"


def test_wheel_easing_is_capped_but_inner_scrollers_are_left_alone():
    """页面本体与侧栏共用一套缓动引擎（2026-11-21 Lenis 调校档，替掉 useScrollSpeedCap）。"""
    hook = read("web/src/motion/useSmoothWheelScroll.ts")
    assert 'from "lenis"' in hook and "new Lenis(" in hook
    assert "const DURATION = 0.85" in hook and "autoRaf: false" in hook
    assert "function frame(" in hook
    assert "node.closest(SELECTOR)" in hook, "页面实例不能接管侧栏里的滚轮"
    assert "prefers-reduced-motion" in hook
    app = read("web/src/App.tsx")
    assert "useSmoothWheelScroll();" in app
    assert "useScrollSpeedCap" not in app
