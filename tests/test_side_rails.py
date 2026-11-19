"""左右侧栏（Agent 工作台 / 稍后再看）的静态守门。

对应方案 docs/side-rails-2026-11-19.md。每条都钉一个真机上翻过的车：
内容列被侧栏挤窄后算错列、右栏把抽屉里的对话又显示一遍、
移出最后一条后撤销条被空态吞掉、详情页右栏关不掉。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_shell_is_the_only_place_that_owns_the_columns():
    """三栏贴边：没有居中壳，也没有两张浮起的圆角卡片。

    照搬的是 B 站 / 小红书 / 抖音的骨架——顶栏通栏，两栏各贴一侧、上下贯通，
    中间那列吃掉剩下的全部宽度。早先 `mx-auto max-w-[1820px] gap-5 px-5` +
    两栏 `rounded-card border` 是一张张浮在纸上的卡片，宽屏上四周一圈空白。
    """
    shell = read("web/src/layout/Shell.tsx")
    app = read("web/src/App.tsx")
    assert "max-w-[1820px]" not in shell, "外层不再有居中壳"
    assert "flex w-full items-start" in shell, "三栏直接铺满视口宽度"
    assert "border-r border-line" in shell, "左栏贴左缘，用一条分隔线收口"
    assert "border-l border-line" in shell, "右栏贴右缘"
    assert "sticky top-[57px]" in shell, "两栏贴着顶栏（56 + 1px 分隔线）往下贯通"
    assert "flex-1 px-6" in shell, "中间列吃掉剩余宽度"
    assert "max-w-[1400px]" in shell, "内容仍有阅读上限，不被超宽屏拉成一条横幅"
    assert "id=\"main\"" in shell
    assert "<AgentSidebar" in shell and "<RightRail" in shell
    assert "<Shell" in app and "<TopBar" not in app, "顶栏归外壳管，App 不该再自己拼"


def test_left_column_follows_measured_width_and_collapses():
    hook = read("web/src/layout/useShell.ts")
    assert "LEFT_FULL = 1200" in hook and "LEFT_RAIL = 960" in hook and "RIGHT_PIN = 1440" in hook
    assert "document.documentElement.clientWidth" in hook
    assert "onefeed.shell.left" in hook, "左栏展开偏好是设备偏好，存本地"
    sidebar = read("web/src/agent/AgentSidebar.tsx")
    assert "collapsed" in sidebar and "PanelLeftClose" in sidebar
    assert "onefeed:rail" in sidebar, "稍后再看入口要能拉起右栏"
    assert "refreshHistory" in sidebar, "左栏列会话只拉列表，不打开历史层"


def test_right_rail_never_duplicates_the_bottom_sheet():
    rail = read("web/src/components/RightRail.tsx")
    assert 'mode === "rail"' in rail, "抽屉形态下右栏不能也跟着显示同一段对话"
    assert 'const presenting = tab === "ai" && agentOpen && mode === "rail"' in rail
    assert 'presenting ? { viewTransitionName: "of-agent" } : undefined' in rail, "名字只在真右栏时挂，避免重复名整段转场被取消"
    surface = read("web/src/agent/AgentSurface.tsx")
    assert "if (onItemPage && pinned) return null;" in surface, "右栏钉住时详情页不要再挂圆钮"


def test_saved_list_keeps_undo_after_the_last_row_leaves():
    saved = read("web/src/components/SavedList.tsx")
    assert "已移出：" in saved and "撤销" in saved
    # 空态与撤销条必须同层：先 return 空态会把撤销一起吞掉（这坑真踩过）
    assert "if (!items.length)" not in saved, "空列表不能提前 return，撤销条会一起消失"
    assert "{items.length ? (" in saved, "列表与空态用三目同层渲染"
    assert "setUndo" in saved and "agentSave(item.id, false)" in saved


def test_brackets_toggle_the_rails_and_escape_closes():
    shell = read("web/src/layout/Shell.tsx")
    assert '"[": shell.toggleLeft' in shell and '"]": shell.toggleRight' in shell
    assert 'useHotkeys("global"' in shell
    assert 'pushScope("dialog")' in shell and 'popScope("dialog")' in shell
    assert "shell.rightOpen" in shell and "setRightOpen(false)" in shell


def test_right_drawer_overlays_instead_of_squeezing_the_feed():
    """窄屏右栏是滑出的抽屉，不再挤内容。

    先在 1280 上试过「让出 364px」，中间列当场掉到 900 以下、三列卡片挤成一条缝，
    收起时内容还要再弹回去一次。抽屉本来就是这个宽度的常见形态，盖上去更稳。
    """
    shell = read("web/src/layout/Shell.tsx")
    assert "drawer-in fixed bottom-0 right-0 top-[57px]" in shell
    assert "pushRight" not in shell and "paddingRight" not in shell, "抽屉不占内容宽度"
    assert "translate-x-full opacity-0" in shell


def test_shell_exposes_column_widths_to_viewport_level_overlays():
    """底部唤起器是 fixed 的：拿不到两栏宽度就会在整屏里居中，跟内容列对不上。

    外壳把两栏实际宽度写成 CSS 变量，唤起器/回顶按钮/抽屉都用它把自己夹在内容列上。
    """
    shell = read("web/src/layout/Shell.tsx")
    assert '"--shell-left-w"' in shell and '"--shell-right-w"' in shell
    for rel in ("web/src/agent/AgentSurface.tsx", "web/src/components/ScrollTop.tsx"):
        src = read(rel)
        assert 'var(--shell-left-w, 0px)' in src and 'var(--shell-right-w, 0px)' in src, rel
    surface = read("web/src/agent/AgentSurface.tsx")
    # 三个挂在视口上的浮层都要夹在内容列里：胶囊、详情页圆钮、抽屉
    for anchor in ('data-agent-launcher-wrap="corner"', 'data-agent-launcher-wrap="pill"', 'data-agent-surface="sheet"'):
        block = surface.split(anchor)[1].split(">")[0]
        assert "var(--shell-left-w, 0px)" in block, anchor + " 没夹在内容列里"


def test_ghost_boxes_follow_the_real_content_column():
    ghost = read("web/src/motion/ghost.ts")
    assert '[data-content]' in ghost and 'getElementById("main")' in ghost, "代位盒子量内容列，量不到才退回 main"
    assert "getBoundingClientRect" in ghost
    assert "CONTENT_MAX" in ghost, "量不到时回落常量"


def test_item_page_hands_its_siblings_to_the_shell_rail():
    item = read("web/src/pages/ItemPage.tsx")
    assert "useRailSlot" in item and "setSiblings" in item
    assert "AgentRail" not in item, "右栏归外壳，详情页不再自己塞一栏"


def test_saved_items_have_a_stable_order_and_timestamp():
    store = read("onefeed/store.py")
    assert "saved_at INTEGER NOT NULL DEFAULT 0" in store
    assert "note TEXT NOT NULL DEFAULT ''" in store
    assert '"saved": f"{SAVED_AT} DESC, i.id DESC"' in store
    assert "UPDATE item_marks SET saved_at = updated_at " in store, "老收藏要迁移出时间"
    assert "WHERE saved = 1 AND saved_at = 0" in store
    api = read("onefeed/api.py")
    assert "sort not in SORTS" in api, "新增排序键后 /api/feed?sort=saved 自动合法"

def test_rail_entries_actually_open_the_column():
    """左栏点「稍后再看 / 收藏夹」必须真把右栏拉开。

    以前只发 onefeed:rail 事件，而这一栏默认关着、组件根本没挂载，
    事件没有接收方——点了像没反应。外壳接住事件再开栏，栏里再切页。
    """
    shell = read("web/src/layout/Shell.tsx")
    assert 'addEventListener("onefeed:rail"' in shell, "外壳要接住左栏的拉栏事件"
    assert "openRight(true)" in shell, "接住之后得真的把右栏打开"
    assert "if (rail) close();" in shell, "Agent 占着这一栏时先收掉，别让列表被对话顶掉"
    rail = read("web/src/components/RightRail.tsx")
    assert '"favorites"' in rail and "FavoritesList" in rail, "右栏要有收藏夹这一页"


def test_favorites_are_a_separate_feature_from_saved():
    """收藏夹 ≠ 稍后再看：两套表、两套接口、两种交互。

    稍后再看是卡片上点星、一键就进、按时间倒序；
    收藏夹在详情页、必须写一句备注、移出还要确认。
    """
    store = read("onefeed/store.py")
    assert "CREATE TABLE IF NOT EXISTS item_favorites" in store, "收藏夹独立建表，不与 item_marks 共用"
    assert "CREATE INDEX IF NOT EXISTS idx_favorites_created" in store
    assert "def favorite_item(" in store and "def favorite_items(" in store
    assert "def get_favorite(" in store and "def unfavorite_item(" in store
    assert "LEFT JOIN item_favorites f" in store

    api = read("onefeed/api.py")
    assert '@router.put("/favorites/{item_id}")' in api, "收藏走独立的 PUT，不复用 mark 接口"
    assert "need_note" in api, "不给备注不许收藏"

    item = read("web/src/pages/ItemPage.tsx")
    assert "FavoriteDialog" in item and "为什么留下它" in item
    assert "confirmDialog({" in item, "移出收藏夹还要过一次确认"
    assert "onefeed:favorites" in item

    favs = read("web/src/components/FavoritesList.tsx")
    assert "favorite_note" in favs, "列表主文是备注，不是标题"
    assert "稍后再看里的状态不受影响" in favs, "移出时说清与稍后再看互不影响"
