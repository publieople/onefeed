"""卡片动作与右栏 AI 总结的静态回归。

这四点都是「加了个入口但没接完」的高发区：
1. 卡片上的星标与三点按钮必须挡住冒泡——卡片本体是 <a>，漏一下就直接跳走；
2. 三点菜单得是真正的 menu：Esc 能关、点外面能关、屏幕下方放不下要翻上去；
3. 「查看 AI 总结」要复用详情页的总结，不是再发一次请求；
4. 右栏的 AI 总结条目来自 /api/agent/summaries，且总结落盘后要自己刷新。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "src"


def read(*parts: str) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


def read_src(*parts: str) -> str:
    return (SRC.joinpath(*parts)).read_text(encoding="utf-8")


CARD = read_src("components", "Card.tsx")
MENU = read_src("components", "CardMenu.tsx")
RAIL = read_src("components", "RightRail.tsx")
SUMMARY_LIST = read_src("components", "SummaryList.tsx")
ITEM = read_src("pages", "ItemPage.tsx")
APP = read_src("App.tsx")
API_TS = read_src("api.ts")
THEME = read_src("theme.css")
SIDEBAR = read_src("agent", "AgentSidebar.tsx")
API_PY = read("onefeed", "api.py")
STORE_PY = read("onefeed", "store.py")

CASES = []


def case(fn):
    CASES.append((fn.__name__, fn))
    return fn


@case
def card_actions_sit_inside_a_link_without_navigating() -> None:
    """卡片是 article + 铺满整张卡的链接；按钮不在 <a> 里，但仍要吞事件。"""
    assert "motion.article" in CARD and 'href={"/item/" + encodeURIComponent(item.id)}' in CARD
    # 第三轮评审 C-04：a > button 是非法嵌套。链接必须是自闭合的一条覆盖层，
    # 内容里不许再出现 </a>（出现就说明按钮又被塞回链接里了）。
    assert "</a>" not in CARD, "卡片里还有 a 包着按钮，重新变成非法嵌套了"
    assert "absolute inset-0 z-0" in CARD, "铺满整张卡的链接不见了"
    assert "pointer-events-auto" in CARD, "页脚按钮没有从「不接指针」的内容层里放出来"
    swallow = CARD.split("const swallow")[1] if "const swallow" in CARD else ""
    assert "preventDefault" in swallow and "stopPropagation" in swallow, "swallow 要同时挡住默认行为与冒泡"
    star = CARD.split('aria-label={isSaved ? "移出稍后再看" : "稍后再看"}')[0]
    more = CARD.split('aria-label="更多操作"')[0]
    assert "swallow(event)" in star.rsplit("onClick", 1)[1], "星标按钮没吞事件"
    assert "swallow(event)" in more.rsplit("onClick", 1)[1], "三点按钮没吞事件"
    assert 'aria-pressed={isSaved}' in CARD
    assert 'aria-haspopup="menu"' in CARD and 'aria-expanded={menuOpen}' in CARD


@case
def card_menu_is_a_real_menu() -> None:
    assert 'role="menu"' in MENU and 'role="menuitem"' in MENU
    assert "createPortal" in MENU, "菜单要挂到 body，别被卡片的 overflow 裁掉"
    assert 'event.key === "Escape"' in MENU or "Escape" in MENU, "Esc 要能关"
    assert "pointerdown" in MENU, "点外面要关"
    assert "rect.top - height" in MENU, "下方放不下要翻到上面"
    assert "ArrowDown" in MENU and "ArrowUp" in MENU, "菜单要能用方向键走"


@case
def card_menu_offers_three_actions() -> None:
    assert '"复制原平台链接"' in CARD
    assert '"查看 AI 总结"' in CARD
    assert "toggleSave(item.id)" in CARD
    # 查看总结直接开详情页，不重复请求
    open_call = CARD.split('"查看 AI 总结"')[1]
    assert "onOpen(item.id," in open_call, "查看总结应复用 onOpen 进详情页"


@case
def copy_link_has_a_fallback_and_a_toast() -> None:
    assert "navigator.clipboard" in CARD
    assert "execCommand(\"copy\")" in CARD and "textarea" in CARD, "剪贴板被拒时要有回落"
    assert 'onefeed:toast' in CARD and "已复制原平台链接" in CARD


@case
def right_rail_has_a_summaries_tab() -> None:
    assert '"summaries"' in RAIL
    assert "SummaryList" in RAIL and "<SummaryList" in RAIL
    assert "AI 总结" in RAIL


@case
def summary_list_reads_the_new_endpoint() -> None:
    assert "agentSummaries(" in SUMMARY_LIST
    assert 'onefeed:summary' in SUMMARY_LIST, "总结写完要自己刷新"
    assert "summary_tldr" in SUMMARY_LIST


@case
def backend_serves_summarized_items() -> None:
    assert '"/agent/summaries"' in API_PY
    assert "summarized_items(" in API_PY
    assert "def summarized_items" in STORE_PY
    assert "JOIN summaries" in STORE_PY or "join_summaries" in STORE_PY.lower() or "summaries s" in STORE_PY
    assert "summary_tldr" in STORE_PY
    # 新路由必须排在 /agent/mark 之前，别被通配吃掉
    assert API_PY.index('"/agent/summaries"') < API_PY.index('"/agent/mark"')


@case
def item_page_announces_finished_summaries() -> None:
    assert 'onefeed:summary' in ITEM
    seg = ITEM.split("onefeed:summary")[1]
    assert "id:" in seg, "事件要带条目 id，右栏才知道刷新谁"


@case
def global_toast_listens_to_card_events() -> None:
    assert 'onefeed:toast' in APP
    assert "setToast" in APP


@case
def sidebar_keeps_two_layers_instead_of_reflowing() -> None:
    assert 'data-shell-layer="full"' in SIDEBAR
    assert 'data-shell-layer="rail"' in SIDEBAR
    assert ".side-layer" in THEME and "transition" in THEME.split(".side-layer")[1][:400]


@case
def theme_vt_merges_the_topbar_into_the_sweep() -> None:
    assert 'html.theme-vt [data-vt="topbar"]' in THEME
    assert "view-transition-name: none" in THEME


@case
def sidebar_footer_links_to_summaries() -> None:
    assert "onefeed:rail" in SIDEBAR
    assert 'tab: "summaries"' in SIDEBAR or "tab:'summaries'" in SIDEBAR
    assert "/api/agent/summaries?limit=1" in SIDEBAR


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print("  PASS", name)
        except AssertionError as exc:
            failed += 1
            print("  FAIL", name, exc)
    print(f"test_card_actions: {len(CASES) - failed}/{len(CASES)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
