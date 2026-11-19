"""列数可配置 + 卡片自适应缩放 + 换列重排的静态守门。

这些断言都对应真机上翻过的车：断点算列、容器查询没接上、
.rise 动画压住 FLIP 的 transform、换列后视口被甩到页首。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_column_count_follows_measured_width_not_viewport_breakpoints():
    hook = read("web/src/layout/useGridCols.ts")
    assert "new ResizeObserver" in hook, "列数要跟网格实测宽度走，侧栏开合才认得出"
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
    assert "clamp(14px, 4.6cqw, 18px)" in theme
    assert "height: 2.84em" in theme, "标题槽位用 em，字号变了等高契约才不破"
    assert "@supports not (container-type: inline-size)" in theme, "老浏览器要有回落"


def test_reflow_animation_survives_the_entry_animation():
    feed = read("web/src/pages/FeedPage.tsx")
    assert "<LayoutGroup" in feed
    assert 'layout="position"' in feed and "layoutDependency={grid.cols}" in feed
    assert "animateLayout = feed.items.length > 0 && feed.items.length <= 48" in feed
    card = read("web/src/components/Card.tsx")
    assert "max-h-[420px]" in card, "单列时封面要封顶，不然一张图吃掉一屏"


def test_switching_columns_keeps_the_reading_position():
    feed = read("web/src/pages/FeedPage.tsx")
    assert "const captureAnchor = () =>" in feed
    assert "getBoundingClientRect().top + window.scrollY" in feed, "要记文档坐标，只记视口 top 会把滚动距离算进补偿量"
    assert "window.scrollBy({ top: delta, behavior: \"auto\" })" in feed
    assert "const chooseCols = (next: ColsChoice) =>" in feed
    assert "onChange={chooseCols}" in feed, "点选和快捷键要走同一条捕获路径"
