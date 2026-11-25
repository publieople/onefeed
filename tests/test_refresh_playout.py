"""刷新演出（清场 → 逐个登场）的守门。

这一层全是「看不见的约定」：相位靠定时器推进、高度靠外层锁住、
布局补间在演出期间必须关掉。任何一条被改回去，界面上表现成
「卡片突然全没了」「页面往上跳一下」「演出卡在半路关不掉」，
但这些都不会让构建失败，所以只能拿测试钉住。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_timeline_constants_match_the_spec():
    tokens = read("web/src/motion/tokens.ts")
    assert "export const REVEAL = {" in tokens
    for key, value in {
        "collapse": "200",
        "gap": "18",
        "hold": "60",
        "base": "160",
        "pop": "300",
        "step": "45",
        "cap": "12",
        "min": "3",
    }.items():
        assert re.search(rf"{key}:\s*{value}\b", tokens), f"REVEAL.{key} 应为 {value}"
    # 总时长要能被相位机算出来（兜底超时 = 总时长 + 400ms）
    assert "export const revealCollapseMs" in tokens
    assert "export const revealPopMs" in tokens
    assert "Math.min(REVEAL.cap" in tokens, "cap 之后同一拍，别让 30 张排成长队"


def test_styles_split_collapse_transition_from_reveal_keyframes():
    theme = read("web/src/theme.css")
    compact = re.sub(r"\s+", "", theme)
    assert ".feed-card[data-out=\"1\"]" in theme
    assert "transition-delay:calc(var(--i,0)*18ms)" in compact, "逆序收靠 --i 的延迟"
    assert "animation-delay:calc(var(--j,0)*45ms)" in compact, "登场阶梯靠 --j 的延迟"
    assert "@keyframes card-pop" in theme and ".feed-card[data-in=\"new\"]" in theme
    assert "@keyframes card-fade" in theme and ".feed-card[data-in=\"carry\"]" in theme
    assert "@keyframes fresh-out" in theme and ".card-fresh" in theme
    # 动效全关的人：不许留任何位移，只保留结果
    reduce = theme[theme.index("@media (prefers-reduced-motion: reduce)") :]
    assert ".feed-card" in reduce and "[data-in]" in reduce


def test_feed_waits_for_a_real_refresh_and_gates_the_show():
    feed = read("web/src/pages/FeedPage.tsx")
    # 只有 refreshSeq 变化才开演：reloadKey 还会被换筛选 / 收藏 / bump 改动
    assert "if (ctx.refreshSeq === playedSeq.current) return;" in feed
    assert "playedSeq.current = ctx.refreshSeq;" in feed
    # 六条闸门
    assert "if (reduceMotion) return;" in feed
    assert 'window.matchMedia("(max-width: 639px)")' in feed, "窄屏不演"
    assert 'document.visibilityState !== "visible"' in feed, "后台标签页不演"
    assert "Date.now() - lastQueryAt.current < 1200" in feed, "刚换过筛选不演"
    assert "if (freshNow.length < REVEAL.min)" in feed, "1–2 条走轻量档，不清场"
    # 序号一到就演、但列表还没换回来 → 会拿着一屏旧卡开演，最后什么都没登场
    assert "if (feed.loadedKey !== ctx.reloadKey) return;" in feed, "数据必须真是这一轮取回来的"
    assert "preRefreshItems.current = feedRef.current.items.slice();" in feed, "收起的是刷新前那一屏"
    assert "setOldItems(preRefreshItems.current.length ? preRefreshItems.current : feed.items);" in feed
    assert "top < -window.innerHeight * 0.6" in feed, "人在列表深处时给胶囊，不拆屏"


def test_feed_locks_height_and_swaps_the_list_by_phase():
    feed = read("web/src/pages/FeedPage.tsx")
    assert "const [lockHeight, setLockHeight]" in feed
    assert "minHeight: lockHeight ? lockHeight + \"px\" : undefined" in feed, "高度锁必须在外层网格上"
    assert "const shownItems = phase === \"collapsing\" && oldItems ? oldItems : feed.items;" in feed
    # waiting 也算收起态：摘掉 data-out 会让刚收下去的旧卡当场淡回来
    assert 'phase === "collapsing" || phase === "waiting"' in feed
    # 兜底：任何相位都不能永久 aria-busy
    assert "window.setTimeout(settle, ms + 400)" in feed
    # 用滚动取消，而不是 inShow 时锁住滚动
    assert 'window.addEventListener("wheel", settle, { passive: true })' in feed
    assert "AnimatePresence" not in feed, "收场不能靠 exit 动画"


def test_progress_pops_out_of_the_button_and_takes_no_room():
    bar = read("web/src/components/RefreshProgress.tsx")
    assert 'data-refresh-bar="1"' in bar
    # 没有运行时宽度归零：以前那 40px 空行正是这次要拆掉的东西
    assert "width: show ? width : 0" in bar, "没东西可显示时宽度必须归零"
    assert "absolute right-full" in bar, "从刷新按钮左侧长出来，不动别的件"
    # 宽度要量出来再补间：绝对定位里 0fr/1fr 会把 1fr 算成 min-content，内容被裁掉
    assert "ResizeObserver" in bar and "offsetWidth" in bar
    assert "grid-cols-[0fr]" not in bar
    assert "h-10" not in bar, "不许再留固定高度的占位"
    assert 'aria-hidden="true"' in bar
    assert "aria-busy={live}" in bar
    assert "onefeed:refresh-dismissed" in bar, "「收起」只隐藏本轮"
    assert "new_total" in bar and "重试失败" in bar
    # 失败详情不能展开在行内：行高一变，正文就会跟着跳
    assert "onefeed:toast" in bar
    # 信息流里不再有那一条占整行的进度带
    assert "RefreshBar" not in read("web/src/pages/FeedPage.tsx")


def test_app_sends_a_separate_refresh_signal():
    app = read("web/src/App.tsx")
    assert "refreshSeq: number;" in app
    assert "if (fresh > 0) setRefreshSeq((k) => k + 1);" in app, "没新增就别演"
    assert "data.state.new_total ??" in app, "新增数用后端算的，别拿 count 累加糊过去"
    assert 'if (location.pathname !== "/")' in app, "信息流由状态条说话，别再用 toast 说第二遍"
    assert "refreshPlatforms" in app and "force: true" in app


def test_card_carries_the_new_marker():
    card = read("web/src/components/Card.tsx")
    assert "reveal?: \"new\" | \"carry\" | null" in card
    assert 'className="card-fresh"' in card



def test_scroll_bottom_checks_auto_and_says_so():
    """滚到底的自动检查走 source=auto：顶栏不动、不演刷新，只在底部报进度和结果。

    这一层最容易被改回去：把 auto 当 user 刷新，整屏会突然收起；
    或者只发请求不说话，用户以为到底就没内容了。
    """
    app = read("web/src/App.tsx")
    feed = read("web/src/pages/FeedPage.tsx")
    api = read("web/src/api.ts")
    assert 'source: "auto"' in app
    assert 'data.state.source === "auto"' in app, "自动检查被当成用户刷新了"
    assert "setAutoKey((k) => k + 1)" in app
    assert "Date.now() - autoAt.current < 10 * 60 * 1000" in app, "10 分钟节流没了"
    assert "autoRefresh: (platforms?: string[]) => void;" in app
    assert 'source: "auto",' in app and "...(platforms?.length ? { platforms } : {})" in app
    # 自动检查只查当前筛选的平台；不传才是全平台
    assert "autoRef.current(autoPlatformsRef.current.length ? autoPlatformsRef.current : undefined);" in feed
    assert "data-auto-refresh" in feed
    assert "正在看看有没有新内容…" in feed and "自动检查完：新增" in feed
    assert "自动检查完：这轮没有新内容" in feed
    assert "看看新增的" in feed
    # 合并新首屏不能换 next：人已经加载好的分页要留着
    assert "export function useFeed(query: FeedQuery, reloadKey: number, autoKey = 0)" in api
    assert "const fresh = new Set(data.items.map((entry) => entry.id));" in api
    assert "return [...data.items, ...prev.filter((entry) => !fresh.has(entry.id))];" in api
    assert "mergeShift" in api and "mergeEpoch" in api


def test_topbar_progress_is_not_a_dead_button():
    topbar = read("web/src/components/TopBar.tsx")
    assert "refreshTitle" in topbar and "正在抓 " in topbar
    assert "disabled={running}" not in topbar, "运行中禁用等于「点了没反应」"
    # 进度就在按钮左边，不用再把人滚到别处去
    assert "scrollIntoView" not in topbar
    assert "hint" in topbar and "RefreshProgress" in topbar, "点了要有回应：让进度件重新亮出来"
    # 进度数字不再只在 md 以上出现
    assert "hidden w-10 text-right text-[11px]" not in topbar
