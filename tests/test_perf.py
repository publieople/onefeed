"""性能回归：几处掉帧点 / 重复请求的守门测试。

对应 docs/perf-audit-2026-11-19.md 的批次 A/B/C。这些断言都盯源码形态，
因为问题本身是「某处常挂了一个会拖慢滚动的属性」「某张表只进不出」这类结构问题，
跑起来才发现的成本太高（要真机 60fps 采样）。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_topbar_has_no_backdrop_filter():
    top = read("web/src/components/TopBar.tsx")
    assert "backdrop-blur" not in top, "顶栏又挂回 backdrop-filter 了：滚动时每帧都要重算背景模糊"
    assert "bg-paper" in top
    assert "data-vt=\"topbar\"" in top


def test_topbar_theme_listener_does_not_rebind_every_frame():
    top = read("web/src/components/TopBar.tsx")
    block = top.split("onefeed:theme")[0]
    assert "}, [theme]);" in top or "}, []);" in top, "主题快捷键的 effect 又变成每帧解绑重绑"
    assert block  # 只是确保切分没把文件切空


def test_page_shell_has_no_screen_wide_will_change():
    css = read("web/src/theme.css")
    shell = css.split(".page-shell")[1].split("}")[0] if ".page-shell" in css else ""
    assert "will-change" not in shell, "4000px 高的容器常挂 will-change 会把整页提升成合成层"


def test_progress_poll_skips_identical_state():
    app = read("web/src/App.tsx")
    assert "function sameRun(" in app
    assert "setProgress((prev) => (sameRun(prev, data.state) ? prev : data.state));" in app


def test_feed_cards_are_memoized_and_layout_animation_is_switchable():
    card = read("web/src/components/Card.tsx")
    assert "export default memo(Card)" in card
    feed = read("web/src/pages/FeedPage.tsx")
    # 包装层只留一种写法：按项数在 div / motion.div 之间切换会让跨过阈值时整批重挂，
    # 现在统一是 motion.div，靠 layout={layoutOn ? "position" : false} 开关。
    assert 'layout={layoutOn ? "position" : false}' in feed
    assert "animateLayout ? (" not in feed, "别再按项数切包装元素"
    assert "const [layoutSettled, setLayoutSettled] = useState(false)" in feed, "换条件时先关布局动画再开，否则重排被 FLIP 拖着走"
    assert "const openItem = useCallback(" in feed, "openItem 不稳，memo 过的卡片每帧都会收到新 props"


def test_saving_one_card_does_not_rerender_the_whole_feed():
    store = read("web/src/agent/savedStore.ts")
    assert "useSyncExternalStore" in store and "subscribe" in store
    card = read("web/src/components/Card.tsx")
    assert "useIsSaved(item.id)" in card, "每张卡只订阅自己那条，点一颗星不该让 30 张卡一起重渲染"
    provider = read("web/src/agent/AgentProvider.tsx")
    assert "savedStore.set" in provider and "savedStore.get" in provider


def test_feed_page_size_stays_small():
    api = read("web/src/api.ts")
    assert 'params.set("limit", "18")' in api, "一页 30 条一次挂 30 张卡，触底就是 226ms 帧 + 191ms 长任务"


def test_hover_prefetch_only_fetches_the_item():
    api = read("web/src/api.ts")
    item_block = api.split("export function prefetchItem(")[1].split("export function prefetchDetail(")[0]
    assert "getDetail(" not in item_block, "悬停别连详情一起拉：慢扫一屏就是十几个重请求"
    assert "/api/item/" in item_block
    detail_block = api.split("export function prefetchDetail(")[1].split("export function peekItem(")[0]
    assert "getDetail(" in detail_block
    card = read("web/src/components/Card.tsx")
    assert "prefetchItem(item.id), 600)" in card, "悬停去抖要够长，否则扫一屏就全在预取"


def test_agent_console_tells_you_it_is_still_working():
    console = read("web/src/components/AgentConsole.tsx")
    assert "quietSeconds" in console and "还在翻，已 " in console, "一轮 Agent 可能十几秒没事件，界面不能一直只写「下一步…」"
    assert 'aria-live="polite"' in console


def test_static_assets_pages_are_code_split():
    app = read("web/src/App.tsx")
    assert 'lazy(() => import("./pages/SettingsPage"))' in app
    assert 'lazy(() => import("./pages/MarketPage"))' in app
    assert 'lazy(() => import("./pages/AgentPage"))' in app
    assert "import ItemPage from" in app, "详情页必须留在主包：转场要在点击后立刻拿到新快照"
    assert "<Suspense" in app


def test_caches_are_bounded():
    api = read("web/src/api.ts")
    assert "PREFETCH_MAX" in api and "function prunePrefetch" in api
    assert "while (feedCache.size > 20)" in api
    assert "while (detailCache.size > 12)" in api


def test_detail_is_cached_for_a_minute():
    api = read("web/src/api.ts")
    block = api.split("export function getDetail(")[1].split("}")[0]
    assert "detailCache.get(id)" in api
    assert "DETAIL_TTL" in api
    assert block


def test_media_is_cacheable_and_revalidates_with_304():
    api = read("onefeed/api.py")
    assert 'out["cache-control"] = "public, max-age=600, stale-while-revalidate=60"' in api
    assert 'request.headers.get("if-none-match") == etag' in api
    assert "status_code=304" in api


def test_images_do_not_queue_behind_video():
    media = read("onefeed/media.py")
    assert "IMAGE_SEMAPHORE = threading.BoundedSemaphore(8)" in media
    assert "def semaphore_for(slot: str):" in media
    api = read("onefeed/api.py")
    assert "sem = media_mod.semaphore_for(slot)" in api
    assert "media_mod.SEMAPHORE.release()" not in api, "还有地方在释放固定的那把视频锁"
