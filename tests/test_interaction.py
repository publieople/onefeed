"""交互层的静态回归：键盘模型、确认框、停靠栏关闭语义、待办状态。

这些点以前都靠人肉点，回归一次就丢一次：
1. 全局快捷键在列表里也能用，只有弹层压顶才让位；
2. 胶囊 ←/→ 只挪焦点不改筛选（以前按一次发一次 /api/feed）；
3. 输入框不在 focus 时展开（P0：focus 展开会弹全屏遮罩吞掉第一次点击）；
4. 关闭不依赖退出动画（动画帧被节流时弹层会卡在 DOM 里）；
5. 破坏性操作一律先问：清 key / 退出登录 / 恢复默认 / 卸载插件 / 删模型行；
6. 异步动作不再共用一个 busy 字符串；
7. 空态按钮得能解决空态（以前 0 条却只给「刷新」）。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "src"


def read(*parts: str) -> str:
    return (SRC.joinpath(*parts)).read_text(encoding="utf-8")


HOTKEYS = read("motion", "useHotkeys.ts")
APP = read("App.tsx")
FEED = read("pages", "FeedPage.tsx")
AGENT = read("agent", "AgentProvider.tsx")
SURFACE = read("agent", "AgentSurface.tsx")
THREAD = read("agent", "AgentThread.tsx")
COMPOSER = read("agent", "AgentComposer.tsx")
AGENT_PAGE = read("pages", "AgentPage.tsx")
ITEM = read("pages", "ItemPage.tsx")
RAIL = read("components", "ui", "TabRail.tsx")
CONFIRM = read("components", "ui", "Confirm.tsx")
HELP = read("components", "ShortcutHelp.tsx")
SETTINGS = read("pages", "SettingsPage.tsx")
MARKET = read("pages", "MarketPage.tsx")
PROVIDERS = read("components", "AiProviders.tsx")
CONSOLE = read("components", "AgentConsole.tsx")

CASES = []


def case(fn):
    CASES.append((fn.__name__, fn))
    return fn


@case
def test_global_scope_survives_list() -> None:
    # 列表压栈时全局键（? / t / r / ⌘K）必须还能用
    # Ctrl+K 页面收得到，但必须 preventDefault，否则地址栏会同时聚焦、焦点被抢走
    assert 'scope === "global" ? top === "dialog" : top !== scope' in HOTKEYS
    assert "e.preventDefault()" in HOTKEYS, "命中快捷键没吞浏览器默认动作"
    for key in ('"/"', '"mod+k"', '"?"', "t:", "r:"):
        assert key in APP, "App 全局快捷键缺 " + key
    assert "pushScope" in APP and "ShortcutHelp" in APP


@case
def test_rail_arrows_only_move_focus() -> None:
    step = RAIL.split("const step =")[1].split("const focusBox")[0]
    # 方向键那一段不能碰筛选；只有 Esc 分支允许重置回「全部」
    arrows = step.split("const keys =")[1]
    assert "ArrowLeft" in arrows and "ArrowRight" in arrows
    assert ".focus()" in arrows and "bring(" in arrows
    assert "choose(" not in arrows, "方向键还在改筛选（键盘用户没法只看不改）"
    assert step.count("choose(") == 1, "方向键分支又在改筛选"
    assert ".focus()" in step and "bring(" in step
    # roving tabindex：只有焦点项可 Tab 到
    assert "tabIndex={(focused ?? primary) === item.id ? 0 : -1}" in RAIL
    # Esc 退回全部
    assert 'event.key === "Escape"' in step


@case
def test_composer_opens_on_click_not_focus() -> None:
    # 输入框只管自己的视觉态；展开由唤起器 / 快捷键 / 发送决定
    assert "onFocus={() => setFocused(true)}" in COMPOSER
    assert "setOpen(true)" not in COMPOSER, "focus 又去展开面板了"


@case
def test_light_layers_close_without_animation() -> None:
    assert "if (!req || !opts) return null;" in CONFIRM, "确认框还在等退出动画"
    assert "AnimatePresence" not in CONFIRM
    assert "if (!open) return null;" in HELP, "快捷键帮助还在等退出动画"
    assert "<AnimatePresence" not in HELP
    # 抽屉 / 右栏 / 全页三处都不靠退出动画关闭
    for src in (SURFACE, THREAD):
        assert "<AnimatePresence" not in src, "轻层又在等 AnimatePresence 收尾"


@case
def test_dock_is_a_dialog() -> None:
    assert 'role="dialog"' in SURFACE and 'aria-modal="true"' in SURFACE
    assert 'aria-live="polite"' in THREAD, "Agent 回复没有 aria-live，读屏听不到"
    assert "FOCUSABLE" in SURFACE and "Tab" in SURFACE, "没有 Tab 陷阱"
    # Esc 由 Provider 统一收，三种形态都生效
    assert 'useHotkeys("dialog", { escape: close }, open)' in AGENT


@case
def test_agent_survives_navigation() -> None:
    # 会话在 Provider 里：换页面（Agent 自己打开的那条）不重建
    assert "<AgentProvider>" in APP, "App 没包 AgentProvider"
    assert "<AgentSurface />" in APP, "唤起器/抽屉没挂到全局"
    assert "AgentProvider" in AGENT and "useState<AgentTurn[]>" in AGENT
    # 详情页右栏 + 上下文上报
    assert '"rail"' in AGENT and '"sheet"' in AGENT and '"closed"' in AGENT
    assert "AgentRail" in ITEM, "详情页没有右栏"
    assert "setFocus({ id: item.id" in ITEM, "详情页没告诉 Agent 在看哪条"
    # 全页形态
    assert 'path="/agent"' in APP and 'path="/agent/:threadId"' in APP
    assert "loadHistory" in AGENT_PAGE and "AgentThreadView" in AGENT_PAGE


@case
def test_destructive_ops_ask_first() -> None:
    # 清 key 要打字确认，其余是普通确认
    assert 'requireTyping: "CLEAR"' in SETTINGS
    for label in ('"清除所有模型 key？"', '"退出这个平台的登录？"', '"把设置改回默认值？"'):
        assert "title: " + label in SETTINGS, "设置里少了一处确认：" + label
    assert "title: \"卸载 \" + id" in MARKET or "卸载 " in MARKET
    assert "confirmDialog" in MARKET and "confirmDialog" in PROVIDERS


@case
def test_pending_is_per_action() -> None:
    assert "useBatchAction<string>()" in MARKET, "市场页又回到一个 busy 字符串了"
    assert "batch.has(" in MARKET
    assert "setBusy(" not in MARKET
    assert "if (!resp.ok) throw new Error(" in SETTINGS, "插件开关又不看响应码了"
    assert "enabled: enabled ? 0 : 1" in SETTINGS, "开关失败没回滚"


@case
def test_settings_baseline_and_unload_guard() -> None:
    assert 'setBaseline("")' not in SETTINGS, "baseline 又被写成空串，dirty 会恒为 false"
    assert 'setBaseline(JSON.stringify(next))' in SETTINGS
    assert "beforeunload" in SETTINGS, "没保存就关页面会静默丢改动"


@case
def test_empty_state_can_actually_help() -> None:
    assert "清空筛选条件" in FEED
    assert 'patch({ platforms: [], keyword: "", range: "all", sort: "", saved: false })' in FEED


@case
def test_list_keyboard_model() -> None:
    assert 'useHotkeys("list"' in FEED
    for key in ("j:", "k:", "h:", "l:", "o:"):
        assert key in FEED, "列表键盘缺 " + key
    assert "preventScroll" in FEED and "scrollIntoView" in FEED
    assert 'pushScope("list")' in FEED


@case
def test_ask_user_answer_round_trip() -> None:
    # 单选：点一下就算答完，别再让用户找第二次「就这个」
    assert 'send([option], "")' in CONSOLE
    # 答过的提问不能在新一轮开始时变回可点（历史里的选项会重新亮起来）
    assert "setAnsweredAsk({})" not in AGENT
    assert "answeredAsk" in THREAD and "onAnswer" in THREAD


@case
def test_saved_view_is_a_filter_not_a_second_page() -> None:
    # 收藏走 URL 筛选（?saved=1），刷新/返回都还在；空态给的是「看全部内容」而不是刷新
    assert 'params.get("saved") === "1"' in FEED
    assert 'sp.set("saved", "1")' in FEED
    assert "还没有收藏" in FEED
    assert "看全部内容" in FEED
    # 卡片上要能看出这条已经收藏了
    CARD = read("components", "Card.tsx")
    assert "item.saved" in CARD


@case
def test_threads_are_resumable_and_saved() -> None:
    # 线程跟页面刷新走：同一段对话才能接着说
    assert "onefeed.agent.thread" in AGENT
    assert "开一段新的" in read("agent", "AgentHistory.tsx")
    assert "listThreads" in AGENT and "getThread" in AGENT
    # 结果卡片带收藏入口（后端 item_marks，不经模型）
    assert "agentSave" in AGENT and 'aria-pressed={saved}' in THREAD


@case
def test_shortcut_help_is_the_single_source() -> None:
    for key in ("/", "⌘ / Ctrl + K", "Esc", "?", "j / k", "← / →"):
        assert key in HELP, "快捷键表里没写 " + key


def main() -> int:
    failed = 0
    for name, fn in CASES:
        try:
            fn()
            print("  PASS", name)
        except AssertionError as exc:
            failed += 1
            print("  FAIL", name, exc)
    print(f"test_interaction: {len(CASES) - failed}/{len(CASES)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
