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
    shell = read("web/src/layout/Shell.tsx")
    app = read("web/src/App.tsx")
    assert '"max-w-[1820px]"' in shell or "max-w-[1820px]" in shell
    assert "max-w-[1180px]" in shell, "中间内容列仍有自己的上限，不被侧栏拉宽"
    assert "id=\"main\"" in shell
    assert "<AgentSidebar" in shell and "<RightRail" in shell
    assert "<Shell" in app and "<TopBar" not in app, "顶栏归外壳管，App 不该再自己拼"


def test_left_column_follows_measured_width_and_collapses():
    hook = read("web/src/layout/useShell.ts")
    assert "LEFT_FULL = 1440" in hook and "LEFT_RAIL = 1024" in hook and "RIGHT_PIN = 1800" in hook
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
    assert "if (onItemPage && pinned) return null;" in surface, "≥1800 右栏常驻，详情页不要再挂圆钮"


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


def test_right_drawer_only_pushes_content_on_wide_screens():
    shell = read("web/src/layout/Shell.tsx")
    assert "pushRight" in shell
    assert "shell.width >= 1280" in shell, "窄屏让不出 364px，只能盖上去"
    assert "paddingRight" in shell


def test_ghost_boxes_follow_the_real_content_column():
    ghost = read("web/src/motion/ghost.ts")
    assert 'getElementById("main")' in ghost, "侧栏挤窄内容列后，代位盒子必须实测"
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
