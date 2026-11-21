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
    # 左栏宽度跟右栏同一套补间：motion 逐帧写 inline width，不是 CSS 过渡。
    # 首帧 initial={false} 直接落在当前宽度，避免重新挂载时从旧值补一遍。
    assert "motion.div" in shell
    assert "initial={false}" in shell
    assert "animate={{ width: leftW }}" in shell
    assert "transition={reduce ? { duration: 0 } : { duration: DUR.page, ease: EASE }}" in shell
    assert "shell-col" in shell
    css = read("web/src/theme.css")
    assert ".shell-col" in css
    col = css.split(".shell-col {")[1].split("}")[0]
    # 宽度既然是逐帧 inline style，就不许再有 CSS 过渡，否则两层动画打架
    assert "transition: none" in col, "列宽同时挂了 CSS 过渡：会和 motion 的 inline width 打架"
    # 中间列的「位移+淡入」是硬切换宽的补丁，宽度补间之后必须删掉，不然叠两层
    assert "content-settle" not in css and "content-settle" not in shell
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
    # 右栏改成「外层动宽度、内层定宽」后，z-40 挂在外层的 motion.div 上
    assert "z-40 flex h-[calc(100vh-57px)] min-h-[420px] shrink-0 justify-end overflow-hidden border-l border-line" in shell
    assert 'className="h-full w-[320px] shrink-0"' in shell


def test_keyframes_and_reduce_motion_are_declared():
    css = read("web/src/theme.css")
    for name in ("sheet-in", "drawer-in"):
        assert "@keyframes " + name in css
        assert "." + name + " {" in css
    assert "animation: sheet-in 0.22s cubic-bezier(0.16, 1, 0.3, 1) backwards" in css
    # backwards：动画结束后不留 fill，收起时 transition 才抢得到 transform
    assert "backwards" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert '[data-shell-drawer="right"],' in css


def test_right_rail_slides_open_with_a_width_tween():
    """右栏进出（2026-11-20）。

    实测过：点 chip 后 t<190ms 右栏还不存在，t=254ms 一帧内 aside 出现、宽度已是 320，
    内容区 1360→1040 同帧完成，然后只剩 opacity 在补 —— 内容「啪」地跳一下。
    光加 opacity 关键帧治不了这个，得让宽度本身逐帧长出来。
    """
    shell = read("web/src/layout/Shell.tsx")
    assert "<AnimatePresence initial={false}>" in shell
    assert "initial={{ width: 0, opacity: 0 }}" in shell
    assert "animate={{ width: RIGHT_W, opacity: 1 }}" in shell
    assert "exit={{ width: 0, opacity: 0 }}" in shell
    # 浮层（AI 球、回顶部）按变量让位。变量只在开合那一刻写一次 ——
    # 逐帧写根元素自定义属性会触发全站样式重算（实测每帧 65–102ms）
    assert 'document.documentElement.style.setProperty("--shell-right-w", (railOpen ? RIGHT_W : 0) + "px")' in shell
    assert "onUpdate" not in shell
    # 浮层自己带 left/right 过渡，别再回来逐帧写变量
    assert "shell-inset-x" in read("web/src/agent/AgentSurface.tsx")
    assert "shell-inset-x" in read("web/src/components/ScrollTop.tsx")
    assert ".shell-inset-x {" in read("web/src/theme.css")
    # 旧做法：只做 opacity 的 keyframes 会让整栏 0ms 挤开内容区，已删
    assert "rail-in" not in read("web/src/theme.css")


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
    """滚轮缓动：Lenis 调校档，页面本体与侧栏共用一套参数与一个 rAF 循环。

    三代演进：① Lenis 默认 lerp 0.09，一格只走 8px、840ms 才停，嫌拖；
    ② 自研两段式（当帧走 62% + 指数收尾），一格 71px 在同一帧落地，
    用户说「还是跳变式」；③ 2026-11-21 从九宫格对照里选了 Lenis 调校档：
    duration 0.85 + easeOutQuart + wheelMultiplier 1，实测一格 38 帧、
    最大单步 6px、613ms 收住。

    钉住：① 六个列表都挂 data-smooth-scroll；② 单条 rAF 驱动全部实例、
    空闲若干帧即停；③ 侧栏到边这一格在捕获阶段拦下、交给页面实例继续缓动，
    不交给浏览器原生滚；④ 模态层打开时 document 捕获阶段全部吞掉；
    ⑤ 程序化滚动与 Mac / reduce 的豁免。
    """
    hook = read("web/src/motion/useSmoothWheelScroll.ts")
    assert "data-smooth-scroll" in hook
    # 参数来自预览页 3 号面板
    assert "const DURATION = 0.85" in hook
    assert "const WHEEL_MULTIPLIER = 1" in hook
    assert "1 - Math.pow(1 - t, 4)" in hook
    assert "duration: DURATION" in hook and "easing: EASING" in hook
    # autoRaf 默认 false，必须自己喂 raf
    assert "autoRaf: false" in hook
    assert "pageLenis.raf(time)" in hook and "lenis.raf(time)" in hook
    # 单条 rAF，连续 IDLE_FRAMES 帧没人滚就停（空闲 0 回调）
    assert "function frame(" in hook and "function kick(" in hook
    assert "idleFrames < IDLE_FRAMES" in hook and "cancelAnimationFrame(rafId)" in hook
    # C-04：暂停改计数，两层模态嵌套时先关的不能把后关的暂停解掉
    assert "pauseDepth += 1" in hook and "Math.max(0, pauseDepth - 1)" in hook
    assert "isPageScrollLocked()" in hook
    # 侧栏到顶/到底：捕获阶段拦下这一格，交给页面实例（不是浏览器原生滚）
    assert "function onBoxWheel(" in hook and "function forwardToPage(" in hook
    assert "stopImmediatePropagation" in hook
    assert "pageLenis.scrollTo(next" in hook
    # 页面实例不接管侧栏里的滚轮（否则两套实例打架）
    assert "node.closest(SELECTOR)" in hook
    # 容器上的 capture 必须在冒泡前，否则容器自己的默认滚动先发生
    assert 'el.addEventListener("wheel", onBoxWheel, { capture: true, passive: false })' in hook
    # 容器上有 scroll-behavior: smooth 时必须 instant 写，否则每帧只挪 2px
    assert 'behavior: "instant" as ScrollBehavior' in hook
    assert "export function scrollInstant" in hook
    assert "scrollInstant(el, el.scrollHeight)" in read("web/src/agent/AgentThread.tsx")
    # 边界放行链接不上 overscroll-contain：CSS 的滚动链会被它截断
    for rel in (
        "web/src/agent/AgentSidebar.tsx",
        "web/src/agent/AgentThread.tsx",
        "web/src/components/SavedList.tsx",
        "web/src/components/SummaryList.tsx",
        "web/src/components/FavoritesList.tsx",
        "web/src/components/RightRail.tsx",
    ):
        assert "overscroll-contain" not in read(rel), rel + " 的 overscroll-contain 会截断边界放行"
    assert "prefers-reduced-motion" in hook
    assert "Mac|iPhone|iPad|iPod" in hook
    assert "usePauseSidebarScroll" in hook
    # 依赖就是 Lenis 本身，参数写死在这里
    assert 'from "lenis"' in hook and "new Lenis(" in hook
    assert '"lenis"' in read("web/package.json")

    app = read("web/src/App.tsx")
    assert "useSmoothWheelScroll()" in app
    assert "useScrollSpeedCap" not in app, "页面限速器已被同一套引擎取代"

    # 模态层盖住整页时，底下的侧栏不该还能被滚轮拖着动
    assert "usePauseSidebarScroll(Boolean(req))" in read("web/src/components/ui/Confirm.tsx")
    assert "usePauseSidebarScroll(true)" in read("web/src/pages/ItemPage.tsx")

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

def test_modals_lock_the_page_scroll():
    """模态层要锁的是 html，不是 body。

    I-05 实测：确认框打开时页面 scrollY 614→1264，灯箱打开时 0→175 ——
    因为灯箱和收藏对话框都只写 document.body.style.overflow，
    而真正承载滚动的是 documentElement。
    """
    lock = read("web/src/motion/useScrollLock.ts")
    assert "document.documentElement" in lock
    assert 'html.style.overflow = "hidden"' in lock
    # 滚动条消失会让整页横向抖一下，用 gutter 顶住
    assert "scrollbarGutter" in lock
    # 计数式：嵌套的两个模态，先关的那个不能把后关的锁解掉
    assert "depth += 1" in lock and "depth > 0" in lock

    item = read("web/src/pages/ItemPage.tsx")
    assert "useScrollLock(true)" in item
    # 旧写法必须清干净，否则两套锁会互相还原成对方的值
    assert "document.body.style.overflow" not in item

    assert "useScrollLock(Boolean(req))" in read("web/src/components/ui/Confirm.tsx")
    assert "useScrollLock(open)" in read("web/src/components/ShortcutHelp.tsx")


def test_page_limit_follows_content_and_lift_keeps_its_transition():
    """两个实测过的回归（2026-11-21）。

    ① 信息流追加卡片只让 body 长高，html 盒尺寸不变 —— Lenis 挂在 documentElement
       上的 ResizeObserver 收不到，limit 冻结在首屏 1916，滚到那儿就再也下不去。
    ② .shell-inset-x 整条写了 transition，把 Tailwind 的 transition duration-300
       顶掉，AI 唤起器收起时 opacity 从 1 直接跳 0（零中间帧）。
    """
    hook = read("web/src/motion/useSmoothWheelScroll.ts")
    assert "function syncPageLimit()" in hook
    assert "pageLenis.limit === pageLimit()" in hook
    assert "bodyObserver.observe(document.body)" in hook
    assert "syncPageLimit();" in hook.split("function forwardToPage")[1][:400]

    css = read("web/src/theme.css")
    lift = css.split(".shell-inset-x.shell-lift {")[1].split("}")[0]
    assert "transform 300ms" in lift and "opacity 300ms" in lift
    sheet = css.split(".shell-inset-x.shell-lift-sheet {")[1].split("}")[0]
    assert "transform 220ms" in sheet and "opacity 220ms" in sheet
    # reduce 下不跑，但节点还在
    assert "  .shell-inset-x.shell-lift,\n  .shell-inset-x.shell-lift-sheet {" in css

    surface = read("web/src/agent/AgentSurface.tsx")
    assert surface.count("shell-inset-x shell-lift ") == 2, "唤起器的两个分支都要带收起过渡"
    assert "shell-inset-x shell-lift-sheet " in surface
    # 旧的 Tailwind 过渡必须清掉：留着也只会被 shell-lift 顶掉，读代码的人会以为它在生效
    assert "transition duration-300 ease-out" not in surface


def test_grid_cols_only_follow_window_width():
    """侧栏开合不许改变信息流列数。

    两版错误做法都实测过：①盯网格自身宽度（ResizeObserver）→ 收左栏内容 +176px，
    3 列 370 当场翻成 4 列 317；②补间期间冻结目标宽度 → 只盖住 300ms 动画，
    补间结束照样翻。现在宽度只在窗口 resize 与挂载（右栏开栏动画落定后补量一次）时更新。
    """
    cols = read("web/src/layout/useGridCols.ts")
    # 只认窗口尺寸：网格自身的 ResizeObserver 必须没有，否则侧栏一推就被重算
    assert "new ResizeObserver" not in cols
    assert 'window.addEventListener("resize"' in cols
    # 挂载后补量一次真实宽度，免得带着右栏刷新时一直按全宽算列
    assert "SETTLE_MS" in cols
    # 冻结层整条拆掉，别再回来
    assert "useGridFreeze" not in cols and "frozen" not in cols
    assert "autoColsFor(width)" in cols

    shell = read("web/src/layout/Shell.tsx")
    assert "freezeGridWidth" not in shell and "gridFreeze" not in shell
    assert not (ROOT / "web/src/layout/gridFreeze.ts").exists()


def test_preflight_runs_the_full_gate():
    """门禁必须一条命令跑完：分散的命令等于没人跑。"""
    sh = read("scripts/preflight.ps1")
    assert "pytest tests -q" in sh
    assert "tests/run_all.py --offline" in sh
    assert "web/scripts/check-ui.mjs" in sh
    assert "npm run build" in sh
    assert '$LASTEXITCODE -ne 0' in sh
