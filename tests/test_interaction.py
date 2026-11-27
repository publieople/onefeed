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
    assert "ShortcutHelp" in APP


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
    # 每个线程一份会话 + 一条独立的事件流，切走不关流、切回能接着看
    assert "AgentProvider" in AGENT
    assert "useState<Record<string, SessionCore>>" in AGENT, "会话又退回全局单份了"
    assert "streamsRef" in AGENT and "sessionsRef" in AGENT, "后台线程没有独立的事件流"
    assert "thread_id: key" in AGENT, "新会话没先铸一个 thread id，切回来会找不到"
    # 详情页右栏 + 上下文上报
    assert '"rail"' in AGENT and '"sheet"' in AGENT and '"closed"' in AGENT
    assert "useRailSlot()" in ITEM and "setSiblings(" in ITEM, "详情页要把同题交给外壳右栏"
    assert "setFocus({ id: item.id" in ITEM, "详情页没告诉 Agent 在看哪条"
    # 全页形态
    assert 'path="/agent"' in APP and 'path="/agent/:threadId"' in APP
    assert "loadHistory" in AGENT_PAGE and "AgentThreadView" in AGENT_PAGE


@case
def test_finished_agent_turn_collapses_its_trace() -> None:
    """跑完的一轮默认只留结果，过程折成一行；想复查再点开。

    以前 trace 一直铺在结果前面，一轮十几步把真正的回答挤到屏幕外，
    用户以为 Agent 还在干活。折叠行仍报「几步 / 多久」，信息没有丢。
    """
    assert "function TraceDisclosure(" in THREAD
    assert "const [open, setOpen] = useState(false);" in THREAD, "过程又默认展开了"
    assert 'data-agent-trace={open ? "open" : "collapsed"}' in THREAD
    assert "aria-expanded={open}" in THREAD and "收起过程" in THREAD
    # 结果在前，过程在后：第一眼看到的是答案，不是步骤
    assert THREAD.index("turn.data ?") < THREAD.index("turn.trace?.length")
    assert "<TraceDisclosure" in THREAD and "<AgentConsole" in THREAD


@case
def test_item_page_agent_opens_from_the_rail_not_the_pill() -> None:
    """详情页点「打开 Agent」，右栏要从右缘长出来，不能从主页底栏的胶囊滑过来。

    以前 openWith 无条件造 pill ghost + runNav("tab")，在详情页会演成
    「底栏横穿整页飞到右边」。详情页没有唤起器可缩，打开/收起都交给栏位自己。
    """
    open_fn = AGENT.split("const openWith")[1].split("const setFocus")[0]
    item_branch = open_fn.split("if (onItemPage) {")[1].split("}")[0]
    assert "setOpen(true);" in item_branch, "详情页没有直接开右栏"
    assert "createGhost" not in item_branch and "runNav(" not in item_branch, "详情页还在演底栏飞行"
    assert open_fn.index("if (onItemPage)") < open_fn.index("createGhost"), "详情页分支必须在造 ghost 之前 return"
    close_fn = AGENT.split("const close = useCallback")[1].split("const openWith")[0]
    assert "if (onItemPage) {" in close_fn
    assert close_fn.index("if (onItemPage)") < close_fn.index("createGhost"), "详情页收起不该缩回胶囊"
    # 主页仍保留唤起器转场
    assert "createGhost({ agent: \"pill\" })" in open_fn


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
    assert "choiceDialog" in SETTINGS and 'secondaryText: "不保存"' in SETTINGS, "站内离开没有保存/不保存/取消三选"


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
def test_history_replay_keeps_results_and_trace() -> None:
    """回放一段旧对话，得跟刚聊完一样有结果卡片和轨迹。

    以前 resumeThread 只铺 input/reply 两行字，done 事件里的 items 被丢掉，
    用户翻历史就只剩「已帮你打开那期」这句话、没有那期本身。
    """
    assert 'event.kind === "done" || event.kind === "cancelled"' in AGENT
    assert 'event.kind !== "delta"' in AGENT, "回放要滤掉流式正文，否则几十帧全塞进 DOM"
    assert "history: true" in AGENT
    # 轨迹里的旧问卷/旧确认不能重新变成可点按钮
    assert "readonly={turn.history}" in THREAD
    assert "const { open: historyOpen }" not in THREAD
    assert "readonly" in CONSOLE and "这轮没等到你的回答" in CONSOLE
    assert "这轮没等到你的确认" in CONSOLE
    # 类型上线程详情要能带事件
    api = read("api.ts")
    assert "events?: AgentEvent[]" in api


@case
def test_shortcut_help_is_the_single_source() -> None:
    for key in ("/", "⌘ / Ctrl + K", "Esc", "?", "j / k", "← / →"):
        assert key in HELP, "快捷键表里没写 " + key


@case
def test_sheet_history_wrapper_is_conditional() -> None:
    """历史收起时那层 flex-1 必须一起卸载。

    以前它一直渲染着：空的 flex-1 会把面板剩余空间全占掉，把对话区挤到底部，
    顶上一大片空白、内容还被裁掉一截（用户截图里「上半部分空白」就是这个）。
    """
    assert "const { open: historyOpen } = useAgentHistory();" in SURFACE
    assert "{historyOpen ? (" in SURFACE
    block = SURFACE.split("{historyOpen ? (")[1].split(") : null}")[0]
    assert "<AgentHistory />" in block, "历史容器应当只在打开时渲染"
    assert "min-h-0 flex-1 overflow-y-auto" in block


@case
def test_agent_surface_transitions() -> None:
    """Agent 三形态之间要有共享元素，而不是整页硬切。

    - 打开/收起：唤起器（胶囊/圆钮）↔ 抽屉，同一个 of-agent 名字做插值；
    - Agent 自己打开一条内容：从右侧代位盒子长成详情页 hero（of-media/of-title），
      跟点卡片是同一套；
    - 收起方向必须把代位盒子挂进新快照（apply 内），否则新页面没有终点；
    - 代位盒子要在 apply 的第一件事摘掉，留到新快照会和真元素同名，浏览器整段跳过转场。
    """
    ghost = read("motion", "ghost.ts")
    nav = read("motion", "nav.ts")
    css = read("theme.css")
    assert "CONTENT_MAX = 1400" in ghost and "export function createGhost" in ghost
    assert 'kind === "corner"' in ghost and "viewTransitionName" in ghost
    # 名字挂在 760 宽的面板上，不是外层通栏容器（否则插值盒子横向铺满整屏）
    sheet = SURFACE.split("data-agent-surface=\"sheet\"")[1]
    assert 'data-vt="agent"' in sheet and 'viewTransitionName: "of-agent"' in sheet
    assert 'data-vt="agent"' in read("agent", "AgentRail.tsx")
    # 唤起器贴内容栏而不是屏幕右沿
    assert "max-w-[1400px]" in SURFACE and 'data-agent-launcher="corner"' in SURFACE
    assert "of-agent" in css and "nav-agent-in" in css
    # 打开用 tab（新侧入场）、收起用 back（旧侧收缩）；prettier 会把 kind 折到下一行，按 token 断言
    for kind in ('"tab"', '"back"', '"push"'):
        assert kind in AGENT, "Agent 转场缺方向 " + kind
    assert "runNav(" in AGENT
    assert "after?:" in nav and "opts.after?.()" in nav
    # 打开条目的两条路径（点卡片 / Agent 自己打开）共用 openItem
    assert "fromAgent: true" in AGENT and "item: seed" in AGENT
    assert "openItem(id, seed)" in AGENT
    # Agent 的 ui_open_item 不许再裸 navigate 绕过转场
    open_branch = AGENT.split('event.name === "ui_open_item"')[1].split("}")[0]
    assert "openItem(" in open_branch and 'navigate("/item/' not in open_branch
    assert "fromAgent" in ITEM and "createGhost" in ITEM
    # 从 Agent 返回信息流时不再给卡片挂名字：同名会让整段转场作废
    assert "backFromAgent" in FEED and "!backFromAgent" in FEED


@case
def test_launcher_fades_into_the_page() -> None:
    """底部唤起器要「淡进纸面」，不能是一颗压在卡片上的实心胶囊。

    - 胶囊下方有一块从纸色到透明的渐隐层（不用 backdrop-blur，那会在长列表上重绘整屏）；
    - 渐隐层不许拦点击，卡片滚到它下面还得能点开；
    - 胶囊平时半透明、薄一点，悬停才浮起来；
    - 内容区底部留白要够，最后一行能滚到渐隐层上面。
    """
    launcher = SURFACE.split('data-agent-launcher="pill"')[1].split("</button>")[0]
    assert "bg-gradient-to-t from-paper" in SURFACE
    assert "pointer-events-none" in SURFACE
    assert "backdrop-blur" not in launcher, "底部条不再用 backdrop-filter"
    assert "bg-paper/80" in launcher and "h-11" in launcher
    assert "hover:-translate-y-0.5" in launcher and "hover:bg-paper" in launcher
    assert 'className="pb-32"' in FEED, "信息流底部要给渐隐层留位置"


@case
def test_card_menu_keeps_keyboard_users_in_place() -> None:
    menu = read("components", "CardMenu.tsx")
    # 首次渲染 pos 还是 null，菜单节点不存在：在 layout effect 里同步 focus 会永远拿到 null
    assert "useEffect(() => {\n    if (!pos) return;" in menu
    assert "hadFocus.current = true" in menu
    assert "anchor.focus({ preventScroll: true })" in menu, "菜单一卸载焦点就掉到 body，键盘用户得从头 Tab 回来"


@case
def test_confirm_dialog_takes_over_the_hotkey_stack() -> None:
    confirm = read("components", "ui", "Confirm.tsx")
    assert "useModalScope(Boolean(req))" in confirm, "确认框开着时 ? / [ 不该还能用"


@case
def test_every_dialog_takes_over_the_hotkey_stack() -> None:
    # 第三轮评审的 C-01：收藏对话框漏了压栈，开着它按 [ 会收左栏、按 t 会切主题。
    # 别再靠人记——凡是 role="dialog" 的组件，都必须自己挂 useModalScope。
    root = ROOT / "web" / "src"
    missing = []
    for path in root.rglob("*.tsx"):
        src = path.read_text(encoding="utf-8")
        if 'role="dialog"' in src and "useModalScope" not in src:
            missing.append(str(path.relative_to(ROOT)).replace("\\", "/"))
    assert not missing, "这些弹层开着时键盘还会漏到页面：" + ", ".join(missing)
    # 计数栈：两层弹窗叠在一起，先关内层不许把外层的 dialog 作用域掀掉
    assert "depth: Record<Scope, number>" in HOTKEYS
    assert "if (depth[target] > 0) return;" in HOTKEYS


# ---------------------------------------------------------------- 总结粒度与条目对话
API = read("api.ts")
LOADER = read("pages", "itemPageLoader.ts")


@case
def test_depth_switch_keeps_the_old_summary() -> None:
    """换档不能把面板清空：先把旧的一份留着，新版到了再换。

    以前 setSummary(null) 直接走骨架，页面上半部分会塌一下再长回来——
    正是他反复说的「不要整页位移」。
    """
    assert "DepthSwitch" in ITEM and 'aria-label="总结粒度"' in ITEM
    assert "aria-pressed" in ITEM
    assert 'layoutId="summary-depth-pill"' in ITEM, "选中态要滑动过去，不是硬切"
    for depth in ('"brief"', '"balanced"', '"detailed"'):
        assert depth in ITEM, "档位缺 " + depth
    # keepOld 只在换档时为真；首次进页面仍然清空（不能把上一条的稿子留在新条目上）
    assert "keepOld" in ITEM and "if (!keepOld) setSummary(null)" in ITEM
    assert "loadSummary(id, false, next, true)" in ITEM
    # 换档期间旧正文留着但压暗，要有进度条说明在重写
    assert 'role="status"' in ITEM and "正在按" in ITEM
    assert "opacity-55" in ITEM
    # 换档失败退回上一份，而不是给空面板
    assert "这里还是上一份" in ITEM


@case
def test_depth_switch_reuses_cache() -> None:
    """切回看过的档位要秒回，不重新跑一遍模型（贵且慢）。"""
    assert "depthCache" in ITEM and "SummaryPayload>" in ITEM
    switch = ITEM.split("const switchDepth")[1].split("\n  };")[0]
    assert "depthCache.current[" in switch and "cached" in switch
    assert "from_cache: true" in switch, "命中的稿子按缓存态展示"
    assert "setBusyDepth" in switch


@case
def test_depth_follows_settings_until_local_choice() -> None:
    """初值跟设置走；本节内点过之后以本地选择为准。"""
    assert "summary_depth" in API and "summary_depth" in SETTINGS
    assert "ctx?.settings?.settings?.summary_depth" in ITEM
    assert "summary?.summary?.depth" in ITEM
    # ItemPage 以前不接 ctx，拿不到设置
    assert "ctx?: OutletCtx" in ITEM
    assert "<ItemPage ctx={ctx}" in APP
    assert "OutletCtx" in LOADER, "懒加载组件的 props 类型要跟 App 一致"


@case
def test_settings_has_default_depth_picker() -> None:
    assert "默认总结粒度" in SETTINGS
    assert 'layoutId="settings-depth-pill"' in SETTINGS
    assert "summary_depth: option.id" in SETTINGS
    assert "DEPTH_OPTIONS" in SETTINGS
    hint = SETTINGS.split("DEPTH_OPTIONS")[1].split("]")[0]
    assert hint.count("hint:") == 3, "每档都要一句说明"


@case
def test_item_page_hands_questions_to_global_agent() -> None:
    """详情页不再挂第二套对话：问题交给右侧全局 Agent，并带上这句话。"""
    assert "问问这条" in ITEM
    assert "useAgentActions" in ITEM and "openWith" in ITEM
    for text in ("最值得记住的是哪一点", "有什么没讲清的地方", "这条和同题其他平台说法一样吗"):
        assert text in ITEM
    assert "打开 Agent" in ITEM
    assert "ItemChat" not in ITEM, "详情页不该再挂独立对话"
    assert not (SRC / "components" / "ItemChat.tsx").exists(), "合并后旧组件要删掉"
    assert "streamItemChat" not in API, "旧客户端流也一起清掉"


@case
def test_platform_chips_follow_installed_plugins() -> None:
    """筛选 chips 要跟已装插件走：只拿 summary 会漏掉已装但还没内容的平台。"""
    assert "health: Health | null;" in APP
    assert "summary, health, settings, reloadSettings, bump," in APP
    assert "ctx.health?.platforms.map((p) => p.platform)" in FEED
    assert "?? ctx.summary?.platforms.map((p) => p.platform)" in FEED


@case
def test_comments_failure_can_be_retried() -> None:
    """评论超时文案写着「稍后可重试」，旁边就必须真有一个重试按钮。"""
    assert "const [commentsRetry, setCommentsRetry] = useState(0);" in ITEM
    assert "}, [id, commentsRetry]);" in ITEM
    assert "setCommentsRetry((n) => n + 1)" in ITEM
    assert "评论没取到" in ITEM and "重试" in ITEM


@case
def test_rules_summary_says_it_is_not_ai() -> None:
    """规则兜底有要点时也不能冒充 AI 总结，面板顶部要写清来源。"""
    assert 'const rulesOnly = Boolean(s && s.engine === "rules" && !s.provider);' in ITEM
    assert "if (rulesOnly && s && !s.points.length)" in ITEM
    assert "这段要点由本地规则整理，还没有用 AI 模型" in ITEM


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
