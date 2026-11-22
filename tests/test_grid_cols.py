"""列数可配置 + 卡片自适应缩放 + 换列重排的静态守门。

这些断言都对应真机上翻过的车：断点算列、容器查询没接上、
.rise 动画压住 FLIP 的 transform、换列后视口被甩到页首。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_column_count_follows_window_width_not_side_rails():
    hook = read("web/src/layout/useGridCols.ts")
    # 反向约定：列数**不能**跟网格自身宽度走。左栏一收内容列 +176px，
    # 3 列 370 会当场翻成 4 列 317 —— 用户点一下侧栏整屏重排。
    assert "new ResizeObserver" not in hook, "列数不许被侧栏开合改写"
    assert 'window.addEventListener("resize"' in hook
    assert "el.clientWidth" in hook
    assert "onefeed.feed.cols" in hook, "列数是设备偏好，存 localStorage，不进 URL"
    assert "CARD_MIN" in hook and "CARD_TARGET" in hook
    feed = read("web/src/pages/FeedPage.tsx")
    assert "md:grid-cols-2" not in feed and "xl:grid-cols-3" not in feed, "断点算列会和侧栏打架"
    assert 'gridTemplateColumns: "repeat(" + grid.cols + ", minmax(0, 1fr))"' in feed
    assert "ref={grid.ref}" in feed
    assert "useGridCols()" in feed


def test_picker_is_discoverable_and_keyboard_reachable():
    picker = read("web/src/components/ui/ColsPicker.tsx")
    assert 'aria-label="每行卡片数"' in picker
    assert "aria-pressed={on}" in picker
    assert "aria-expanded={open}" in picker
    assert "最多 {maxFit} 列" in picker, "宽度不够的档位要明说，不要静默降级"
    assert 'useHotkeys("dialog", { escape: () => setOpen(false) }, open)' in picker
    feed = read("web/src/pages/FeedPage.tsx")
    for digit in "012345":
        assert '"alt+' + digit + '"' in feed, "Alt+数字 要能直接定列数"
    assert "<ColsPicker" in feed


def test_cards_scale_with_their_own_width():
    card = read("web/src/components/Card.tsx")
    assert 'containerType: "inline-size"' in card
    assert "card-title" in card and "card-meta" in card, "字号要按卡片宽度走，不能写死"
    theme = read("web/src/theme.css")
    # 分档 @container 而不是连续 cqw：连续缩放会让左栏收放的每一帧都给 30 张卡换字号，
    # 实测一次收栏 240ms 长任务（26fps），分档之后只剩盒宽变化。
    assert "@container (min-width: 250px)" in theme
    assert "@container (min-width: 600px)" in theme
    assert "cqw, 18px" not in theme and "4.6cqw" not in theme, "字号别再跟 cqw 连续缩放"
    assert "height: 2.84em" in theme, "标题槽位用 em，字号变了等高契约才不破"
    assert "@supports not (container-type: inline-size)" in theme, "老浏览器要有回落"


def test_breakpoints_avoid_the_width_the_left_rail_sweeps_through():
    """左栏收放会扫过 371→427 这一区间，断点落在这里等于每次收放都重排全部卡片。"""
    theme = read("web/src/theme.css")
    import re

    stops = [int(m) for m in re.findall(r"@container \(min-width: (\d+)px\)", theme)]
    assert stops, "至少要有一档容器断点"
    sweeps = range(360, 440)
    for stop in stops:
        assert stop not in sweeps, f"{stop}px 落在左栏收放的扫过区间，会每帧跨档"


def test_reflow_animation_survives_the_entry_animation():
    feed = read("web/src/pages/FeedPage.tsx")
    assert "<LayoutGroup" in feed
    assert "layoutDependency={grid.cols}" in feed
    assert "animateLayout = feed.items.length > 0 && feed.items.length <= 48" in feed
    # 进场动画挂在内层 .rise：挂外层会压住 FLIP 写的 transform（fill-mode: both）。
    # 现在内层还要承载「收场 / 登场」两个相位（feed-card + data-out/data-in），
    # 而 .rise 只在非演出态、且这张卡还没登场过时挂上。
    assert 'className={"feed-card relative h-full " + rise}' in feed
    assert "animatedIds.current.has(item.id)" in feed, "登场过的卡不能再淡一次"
    card = read("web/src/components/Card.tsx")
    assert "max-h-[420px]" in card, "单列时封面要封顶，不然一张图吃掉一屏"


def test_switching_columns_keeps_the_reading_position():
    feed = read("web/src/pages/FeedPage.tsx")
    assert "const captureAnchor = () =>" in feed
    assert "getBoundingClientRect().top + window.scrollY" in feed, "要记文档坐标，只记视口 top 会把滚动距离算进补偿量"
    assert "window.scrollBy({ top: delta, behavior: \"auto\" })" in feed
    assert "const chooseCols = (next: ColsChoice) =>" in feed
    assert "onChange={chooseCols}" in feed, "点选和快捷键要走同一条捕获路径"
