import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { LayoutGroup, motion, useReducedMotion } from "framer-motion";
import { ArrowUp, Bookmark, Loader2, RefreshCw, Star } from "lucide-react";
import type { OutletCtx } from "../App";
import { prefetchDetail, useFeed, type FeedItem } from "../api";
import { DEMO } from "../demo";
import Card from "../components/Card";
import Chips from "../components/Chips";
import ColsPicker from "../components/ui/ColsPicker";
import { useGridCols, type ColsChoice } from "../layout/useGridCols";
import { itemPageLoaded, loadItemPage } from "../pages/itemPageLoader";
import { runNav } from "../motion/nav";
import { DUR, EASE, REVEAL, revealCollapseMs, revealPopMs } from "../motion/tokens";
import { useHotkeys, pushScope, popScope } from "../motion/useHotkeys";

interface Props {
  ctx: OutletCtx;
}

export default function FeedPage({ ctx }: Props) {
  // 筛选条件是 URL 的一部分：刷新、分享链接、从详情页返回都还认得这套条件
  const [params, setParams] = useSearchParams();
  const selected = useMemo(() => (params.get("p") ?? "").split(",").filter(Boolean), [params]);
  const q = params.get("q") ?? "";
  const sort = params.get("sort") ?? "";
  const range: "all" | "today" = params.get("range") === "today" ? "today" : "all";
  const savedOnly = params.get("saved") === "1";
  const patch = (next: {
    platforms?: string[];
    keyword?: string;
    sort?: string;
    range?: "all" | "today";
    saved?: boolean;
  }) => {
    const sp = new URLSearchParams(params);
    if (next.platforms) {
      if (next.platforms.length) sp.set("p", next.platforms.join(","));
      else sp.delete("p");
    }
    if (next.keyword !== undefined) {
      if (next.keyword.trim()) sp.set("q", next.keyword);
      else sp.delete("q");
    }
    if (next.sort !== undefined) {
      if (next.sort) sp.set("sort", next.sort);
      else sp.delete("sort");
    }
    if (next.range !== undefined) {
      if (next.range === "today") sp.set("range", "today");
      else sp.delete("range");
    }
    if (next.saved !== undefined) {
      if (next.saved) sp.set("saved", "1");
      else sp.delete("saved");
    }
    setParams(sp, { replace: true });
  };
  const navigate = useNavigate();
  const location = useLocation();
  // 从详情页返回时，详情页要缩回这张卡片：它得先在场，还要在视野里
  const backId = (location.state as { fromId?: string } | null)?.fromId ?? null;
  // Agent 打开的条目返回时用的是右侧代位盒子，页面上那张卡不参与转场，
  // 也就不该给它挂名字（同名会让浏览器整体跳过转场），更不用滚到它那儿。
  const backFromAgent = Boolean((location.state as { fromAgent?: boolean } | null)?.fromAgent);
  const restoreAnchor = (): (() => void) | undefined => {
    if (!backId || backFromAgent) return;
    const find = () => document.querySelector<HTMLElement>('[data-vt-item="' + CSS.escape(backId) + '"]');
    // 焦点也要跟着回来：详情页那个 h1 已随路由卸载，不还的话键盘用户落在 body 上。
    // 只做一次（图片撑高会反复触发下面的重锚，反复抢焦点会打架）。
    let focused = false;
    const focusCard = () => {
      if (focused) return;
      const link = find()?.querySelector<HTMLElement>('a[href^="/item/"]');
      if (!link) return;
      link.focus({ preventScroll: true });
      focused = true;
    };
    const seek = () => {
      find()?.scrollIntoView({ block: "center", behavior: "auto" });
      focusCard();
    };
    seek();
    // 缓存没命中、或者图片后来把卡片撑高，落点都会偏；数据到位和尺寸变化时各补一次
    const raf = requestAnimationFrame(seek);
    const timer = window.setTimeout(seek, 240);
    let ro: ResizeObserver | null = null;
    const el = find();
    if (el && typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver(() => seek());
      ro.observe(el);
    }
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
      ro?.disconnect();
    };
  };
  // 卡片先放大再进详情：把被点的元素作为过渡的那一层。
  // 同时把现在的地址（含筛选条件）交给详情页，返回时才能回到同一屏。
  const openItem = useCallback((id: string, el?: HTMLElement, seed?: FeedItem) => {
    // 转场要 420ms，这段时间足够把详情请求排上队；点下去才算真意图，不算网络放大
    prefetchDetail(id);
    // 卡片里的媒体框和标题是共享元素的两端：给它们挂上名字，浏览器才知道这两块要「长大」
    const media = el?.querySelector<HTMLElement>('[data-vt="media"]') ?? null;
    const title = el?.querySelector<HTMLElement>('[data-vt="title"]') ?? null;
    const go = () =>
      runNav(
        "push",
        () => {
          navigate("/item/" + encodeURIComponent(id), {
            // seed：卡片手里已经有这条数据，详情页拿它垫首屏 —— 新快照里立刻就有
            // 媒体框和标题这两个共享元素，转场才有两端可插值（不然只剩整页淡出）
            state: { vt: true, from: location.pathname + location.search, fromId: id, item: seed },
          });
          // 进详情从头看；App 的切页滚动对 vt 跳转已让位，这里在快照前滚好
          window.scrollTo({ top: 0, behavior: "auto" });
        },
        {
          names: [
            { el: media, name: "of-media" },
            { el: title, name: "of-title" },
          ],
        },
      );
    // 详情页现在是独立 chunk：模块没就位就起转场，新快照会是一屏 Suspense 骨架。
    // 悬停预热的正常路径这里直接放行；冷点只多等一次模块下载。
    if (itemPageLoaded()) {
      go();
      return;
    }
    void loadItemPage().then(go);
    // 稳定引用：否则 memo 过的卡片每帧都收到新 onOpen，白 memo
  }, [navigate, location.pathname, location.search]);

  const activeSort = sort || ctx.settings?.settings.default_sort || "freshness";
  const since = useMemo(() => {
    if (range !== "today") return null;
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return Math.floor(d.getTime() / 1000);
  }, [range]);
  const query = useMemo(
    () => ({ platforms: selected, kind: "", sort: activeSort, q, since, saved: savedOnly }),
    [selected, activeSort, q, since, savedOnly],
  );
  const feed = useFeed(query, ctx.reloadKey, ctx.autoKey);
  // 列数按网格实测宽度算（侧栏开合、窗口缩放都走这条），不再用 md:/xl: 视口断点
  const grid = useGridCols();
  const active = selected.length > 0 || q.trim().length > 0 || savedOnly;
  // 筛选 chips = 有内容的平台（含旧内容）+ 已装但还没抓过的平台；health 失败时回退摘要。
  const chipPlatforms = ctx.health
    ? Array.from(new Set([
        ...ctx.health.platforms.map((p) => p.platform),
        ...(ctx.health.plugin_ids ?? []),
      ]))
    : ctx.summary?.platforms.map((p) => p.platform);
  // 重排动画覆盖「换列数 / 侧栏开合 / 换筛选」三种情况。项数多时逐张滑太拖，
  // 所以 48 张封顶（一屏半的量），再多就直接换 —— 连 motion 节点都不建。
  // 系统里关掉动效的人，换列就直接到位。
  const reduceMotion = useReducedMotion();
  // 重排动画留给「列数变了」——那才是卡片自己挪了地方。换筛选 / 排序是整批换内容，
  // 30 张卡各挂一套布局测量只换来 160–190ms 的长任务。整块按查询重挂一次，
  // FLIP 就没有旧投影可对，新卡片用 .rise 进场，跟换了一屏的样子正好对上。
  const queryKey = JSON.stringify(query);
  const animateLayout = feed.items.length > 0 && feed.items.length <= 48 && !reduceMotion;
  /**
   * 换筛选 / 排序的这一刻不要 FLIP：整批内容都换了，没有「同一张卡从 A 挪到 B」
   * 这回事，但 30 张卡各挂一套投影测量会换来 160–190ms 的长任务。
   * 等这一屏落定再把投影打开 —— 之后换列数才是真需要它的时候。
   *
   * （包装层始终是 motion.div，只切 layout 的值。按项数换 <div>/<motion.div>
   * 会让 30 张卡在跨过 48 张那条线时整批重挂，触底加载实测 213ms 就是这么来的。）
   */
  const [layoutSettled, setLayoutSettled] = useState(false);
  useEffect(() => {
    setLayoutSettled(false);
    const timer = window.setTimeout(() => setLayoutSettled(true), 420);
    return () => window.clearTimeout(timer);
  }, [queryKey, feed.items.length]);
  const layoutOn = animateLayout && layoutSettled;

  // ---------------------------------------------------------------- 刷新演出
  /**
   * 清场 → 逐个登场。相位只靠 setTimeout 推进，不挂 onAnimationComplete：
   * 隐藏页 / 掉帧时动画完成事件不一定来，卡在半路就等于 aria-busy 永远为 true。
   */
  const [phase, setPhase] = useState<"idle" | "collapsing" | "waiting" | "revealing">("idle");
  const [oldItems, setOldItems] = useState<FeedItem[] | null>(null);
  const [freshIds, setFreshIds] = useState<Set<string> | null>(null);
  const [lockHeight, setLockHeight] = useState<number | null>(null);
  const [pill, setPill] = useState<number | null>(null);
  // 演到哪一轮了：refreshSeq 只在「刷新结束且本轮有新增」时变，不能拿 reloadKey 顶替
  const playedSeq = useRef(0);
  const oldIds = useRef<Set<string>>(new Set());
  const captured = useRef<FeedItem[] | null>(null);
  // 返回首页时 FeedPage 是重挂的；缓存里这批卡离开前已经入过场了，先记成已入场，
  // 否则 18 张卡会一起重播 .rise，看起来像整屏又在加载。
  const animatedIds = useRef<Set<string>>(new Set(feed.items.map((item) => item.id)));
  const feedRef = useRef(feed);
  feedRef.current = feed;
  const freshTimer = useRef<number | null>(null);
  const lastQueryAt = useRef(0);
  // 刷新序号一变就先记下「这一屏原来有哪些」，之后列表换成新数据时才有得比。
  // 等到数据回来再记就晚了：那时新旧已经在同一个数组里，谁也分不出来。
  const preRefreshIds = useRef<Set<string>>(new Set());
  const preRefreshItems = useRef<FeedItem[]>([]);

  // 「这一轮 query 没变」的判据：换筛选的那一刻记时间。演出一看它就知道用户
  // 是不是刚换过条件 —— 换了就别演，否则收场会跟换筛选的 layout 补间抢同一批卡片。
  useEffect(() => {
    lastQueryAt.current = Date.now();
  }, [queryKey]);

  const settle = useCallback(() => {
    setPhase("idle");
    setOldItems(null);
    setLockHeight(null);
  }, []);

  const reveal = useCallback(() => {
    const list = feedRef.current.items;
    const fresh = new Set(list.filter((item) => !oldIds.current.has(item.id)).map((item) => item.id));
    list.forEach((item) => animatedIds.current.add(item.id));
    setFreshIds(fresh);
    setPhase("revealing");
    if (freshTimer.current) window.clearTimeout(freshTimer.current);
    // 「新」标记由 CSS 在 2.4s 淡出，这里到点只把节点摘掉
    freshTimer.current = window.setTimeout(() => setFreshIds(null), 2600);
  }, []);

  useEffect(
    () => () => {
      if (freshTimer.current) window.clearTimeout(freshTimer.current);
    },
    [],
  );

  const showNew = useCallback(() => {
    if (feedRef.current.loading) return;
    window.scrollTo({ top: 0, behavior: "auto" });
    setPill(null);
    reveal();
  }, [reveal]);

  // 序号一落地就冻结「旧的一屏」。此刻列表还是刷新前的那批（重新取数要等网络），
  // 晚一步记就会把新旧混在一起。
  useEffect(() => {
    if (ctx.refreshSeq === playedSeq.current) return;
    preRefreshIds.current = new Set(feedRef.current.items.map((item) => item.id));
    preRefreshItems.current = feedRef.current.items.slice();
  }, [ctx.refreshSeq]);

  // 开演判定。ctx.refreshSeq 只有「刷新真的结束且本轮有新增」才变，
  // reloadKey 还会被换筛选、收藏、bump 改动，拿它当信号会把换筛选也演一遍。
  useEffect(() => {
    if (ctx.refreshSeq === playedSeq.current) return;
    if (feed.loading || feed.items.length === 0) return;
    if (phase !== "idle") return;
    // 列表必须确实是这一轮刷新取回来的：序号变了但数据还在路上时开演，
    // 收起的是旧卡、登场时却找不到任何新条目，演出会变成「全收起来再全淡回来」。
    if (feed.loadedKey !== ctx.reloadKey) return;
    playedSeq.current = ctx.refreshSeq;

    const total = Number(ctx.progress?.new_total ?? 0);
    if (total <= 0) return;
    // 条件 5：关掉动效的人、以及窄屏（一列卡片收放更像卡了）
    if (reduceMotion) return;
    if (window.matchMedia("(max-width: 639px)").matches) return;
    // 条件 6：后台标签页里播完，切回来只剩结果，用户什么都没看见
    if (document.visibilityState !== "visible") return;
    // 条件 3：刚换过筛选就不演
    if (Date.now() - lastQueryAt.current < 1200) return;

    oldIds.current = preRefreshIds.current;
    const freshNow = feed.items.filter((item) => !oldIds.current.has(item.id));
    // 本轮新增在首屏里一条都没露脸（比如都排到第二屏去了）：没有可登场的东西
    if (freshNow.length === 0) return;
    captured.current = feed.items;
    feed.items.forEach((item) => animatedIds.current.add(item.id));

    const top = grid.ref.current?.getBoundingClientRect().top ?? 0;
    const box = grid.ref.current?.offsetHeight ?? 0;

    if (freshNow.length < REVEAL.min) {
      // 轻量档：1–2 条不值得清场，就地弹一下
      setLockHeight(null);
      setOldItems(null);
      reveal();
      return;
    }
    if (top < -window.innerHeight * 0.6) {
      // 条件 2：人在列表深处。当着他的面拆掉整屏，回来会发现全变了 → 先给胶囊
      setPill(total);
      return;
    }
    // 锁高：收场时总高度会缩，页面下方被往上拽；缩到比视口还短时浏览器还会夹一次 scrollY
    setLockHeight(box);
    setPill(null);
    // 收起的是「刷新前那一屏」：新卡这时候还没登场，不该跟着一起收
    setOldItems(preRefreshItems.current.length ? preRefreshItems.current : feed.items);
    setPhase("collapsing");
    // 焦点别掉到 body：此刻焦点若在这批卡片里，先交给网格（section 带 tabIndex=-1）
    if (grid.ref.current && grid.ref.current.contains(document.activeElement)) {
      grid.ref.current.focus({ preventScroll: true });
    }
  }, [ctx.refreshSeq, ctx.progress?.new_total, ctx.reloadKey, feed.loading, feed.loadedKey, feed.items, phase, reduceMotion, grid.ref, reveal]);

  useEffect(() => {
    if (phase === "idle" || phase === "waiting") return;
    const count = phase === "collapsing" ? oldItems?.length ?? 0 : feed.items.length;
    const ms =
      phase === "collapsing"
        ? revealCollapseMs(count)
        : phase === "revealing"
          ? revealPopMs(count)
          : REVEAL.base;
    const step = window.setTimeout(() => {
      if (phase === "collapsing") {
        // 数据都到齐了（开演前就校验过 loadedKey），这里只剩「等到点」；
        // 万一中途又触发了取数，等一拍再登场，别让旧卡先淡回来
        if (feedRef.current.loading) setPhase("waiting");
        else reveal();
        return;
      }
      settle();
    }, ms);
    // 兜底：动画帧被节流、或者某个 keyframes 没跑，也不能永久 aria-busy
    const guard = window.setTimeout(settle, ms + 400);
    return () => {
      window.clearTimeout(step);
      window.clearTimeout(guard);
    };
  }, [phase, oldItems, feed.items, reveal, settle]);

  // 收起完了数据还没回来：每 120ms 看一眼，最多等 1.8s 就按新数据直接落地
  useEffect(() => {
    if (phase !== "waiting") return;
    const start = Date.now();
    const timer = window.setInterval(() => {
      const current = feedRef.current;
      if (!current.loading && current.items !== captured.current) {
        window.clearInterval(timer);
        reveal();
        return;
      }
      if (Date.now() - start > 1800) {
        window.clearInterval(timer);
        settle();
      }
    }, 120);
    return () => window.clearInterval(timer);
  }, [phase, reveal, settle]);

  // 演出期间不加滚动锁：用户一动就算结算，别把人按在半空中
  useEffect(() => {
    if (phase === "idle") return;
    window.addEventListener("wheel", settle, { passive: true });
    window.addEventListener("touchmove", settle, { passive: true });
    window.addEventListener("keydown", settle);
    return () => {
      window.removeEventListener("wheel", settle);
      window.removeEventListener("touchmove", settle);
      window.removeEventListener("keydown", settle);
    };
  }, [phase, settle]);

  // 胶囊是保底入口，没人点就自己退场
  useEffect(() => {
    if (pill === null) return;
    const timer = window.setTimeout(() => setPill(null), 12000);
    return () => window.clearTimeout(timer);
  }, [pill]);

  const inShow = phase !== "idle";
  const shownItems = phase === "collapsing" && oldItems ? oldItems : feed.items;

  // 列数一变，文档高度跟着变：浏览器只会把视口钉在原来的滚动偏移上，
  // 正在看的那张卡就被甩出屏幕了。换列前记下「第一张还在视野里的卡」在文档里的位置，
  // 换完按它的位移补一次滚动 —— 换列才像卡片自己挪了地方，而不是页面跳一下。
  // 记的是文档坐标（视口 top + scrollY），否则补偿量会把当前滚动距离算进去。
  const anchor = useRef<{ id: string; docTop: number; cols: number } | null>(null);
  const captureAnchor = () => {
    const first = Array.from(document.querySelectorAll<HTMLElement>("[data-vt-item]")).find(
      (el) => el.getBoundingClientRect().bottom > 0,
    );
    anchor.current = first
      ? { id: first.dataset.vtItem ?? "", docTop: first.getBoundingClientRect().top + window.scrollY, cols: grid.cols }
      : null;
  };
  const chooseCols = (next: ColsChoice) => {
    captureAnchor();
    grid.setChoice(next);
  };
  useLayoutEffect(() => {
    const prev = anchor.current;
    if (!prev || prev.cols === grid.cols) return;
    if (document.documentElement.classList.contains("vt-running")) return;
    const el = document.querySelector<HTMLElement>('[data-vt-item="' + CSS.escape(prev.id) + '"]');
    if (!el) return;
    const delta = el.getBoundingClientRect().top + window.scrollY - prev.docTop;
    if (Math.abs(delta) > 4) window.scrollBy({ top: delta, behavior: "auto" });
  }, [grid.cols]);

  // ── 列表键盘模型：j/k 上下、h/l 跨列、o 新标签打开、Enter 交给原生 <a>
  const [cursor, setCursor] = useState(-1);
  const cardEls = () => Array.from(document.querySelectorAll<HTMLAnchorElement>('[data-vt-item] a[href^="/item/"]'));
  const moveCursor = (delta: number) => {
    setCursor((prev) => {
      const last = feed.items.length - 1;
      if (last < 0) return -1;
      // 还没进列表时，往下从第一张开始，往上从最后一张开始
      if (prev < 0) return delta > 0 ? 0 : last;
      return Math.min(last, Math.max(0, prev + delta));
    });
  };
  useEffect(() => {
    if (cursor < 0) return;
    const el = cardEls()[cursor];
    if (!el) return;
    el.focus({ preventScroll: true });
    // 连按 j/k 时「啪、啪」地瞬移很晕；smooth 让镜头跟着光标滑过去，
    // 后一次按键会重定目标，不会排一串动画。
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursor]);
  // 换筛选等于换了一屏卡片，光标要归零，否则 f/j 会跳到别的条目上
  useEffect(() => {
    setCursor(-1);
  }, [query]);

  const current = () => {
    const list = cardEls();
    if (cursor >= 0 && cursor < list.length) return list[cursor];
    const activeEl = document.activeElement;
    return activeEl instanceof HTMLAnchorElement ? activeEl : list[0] ?? null;
  };

  useHotkeys("list", {
    j: () => moveCursor(1),
    k: () => moveCursor(-1),
    l: () => moveCursor(grid.cols),
    h: () => moveCursor(-grid.cols),
    // Alt+0~5 直接定列数：不用 Ctrl/⌘+数字，那是 Chrome 切标签页的
    "alt+0": () => chooseCols("auto"),
    "alt+1": () => chooseCols(1),
    "alt+2": () => chooseCols(2),
    "alt+3": () => chooseCols(3),
    "alt+4": () => chooseCols(4),
    "alt+5": () => chooseCols(5),
    o: () => {
      const el = current();
      if (el) window.open(el.href, "_blank", "noopener");
    },
  });
  // 列表作用域：AI 面板 / 帮助层压上来时，j/k 自动让位（useHotkeys 只看栈顶）
  useEffect(() => {
    pushScope("list");
    return () => popScope("list");
  }, []);

  // 从详情页返回：等这一屏的卡片真的在页面上了，再把目标卡片滚到中间。
  // 只在首帧找一次是不够的——缓存没命中时卡片还没渲染，图片撑高也会让落点跑偏。
  useLayoutEffect(() => {
    if (!backId) return;
    restoreAnchor();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backId, feed.loading, feed.items.length]);

  // ── 触底：先无限预取下一页；真的到最底了，再自动去各平台看一眼有没有新内容。
  // 传感器一直挂在底部状态条上，所以「已经到底了」也能成为自动检查的落点。
  // 回调里读 ref：feed.more / autoRefresh 每次渲染都是新函数，直接进依赖会让 observer 反复重建。
  const sentinel = useRef<HTMLDivElement | null>(null);
  const moreRef = useRef(feed.more);
  moreRef.current = feed.more;
  const nextRef = useRef(feed.next);
  nextRef.current = feed.next;
  const autoRef = useRef(ctx.autoRefresh);
  autoRef.current = ctx.autoRefresh;
  // 自动检查跟着当前筛选走：筛了 V2EX 就只查 V2EX，新增数才对得上这一屏。
  const autoPlatformsRef = useRef<string[]>([]);
  autoPlatformsRef.current = selected;
  const autoReadyRef = useRef(false);
  autoReadyRef.current =
    !DEMO &&
    !feed.next &&
    !feed.loading &&
    !feed.moreLoading &&
    !ctx.autoRunning &&
    !ctx.progress?.running &&
    feed.items.length > 0;
  // 首屏没滚过就不算「往下滑」：短文列表不该一进来就去打平台。
  // 用 state 而不是 ref：一屏只有几条时传感器首帧就在视野里，observer 回调先跑、
  // 那时还没滚过；等真滚了必须把 observer 重建一次，否则它不会再回来问。
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => {
      if (window.scrollY > 120) setScrolled(true);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") return;
    let autoTimer = 0;
    const io = new IntersectionObserver(
      (entries) => {
        if (!entries.some((entry) => entry.isIntersecting)) return;
        if (nextRef.current) {
          void moreRef.current();
          return;
        }
        if (!autoReadyRef.current || !scrolled) return;
        // 稍等一下：触底那一下经常还在惯性滚动，别在飞行途中又起一轮采集。
        window.clearTimeout(autoTimer);
        autoTimer = window.setTimeout(() => {
          if (autoReadyRef.current) {
            autoRef.current(autoPlatformsRef.current.length ? autoPlatformsRef.current : undefined);
          }
        }, 600);
      },
      { rootMargin: "0px 0px 1200px 0px" },
    );
    io.observe(el);
    return () => {
      window.clearTimeout(autoTimer);
      io.disconnect();
    };
  }, [feed.next, feed.items.length, ctx.autoRunning, ctx.progress?.running, ctx.autoKey, scrolled]);

  // 一屏都没铺满（筛选后只剩几条）时传感器够不着，自己补一次，别让人对着空荡荡的页面
  useEffect(() => {
    if (!feed.next || feed.loading || feed.moreLoading) return;
    if (document.documentElement.scrollHeight > window.innerHeight + 240) return;
    const timer = window.setTimeout(() => {
      if (nextRef.current) void moreRef.current();
    }, 80);
    return () => window.clearTimeout(timer);
  }, [feed.next, feed.loading, feed.moreLoading, feed.items.length]);

  // 自动检查把首屏新条目插到了上面：按高度差把滚动位置补回来，
  // 人停在原地看的那几张卡不因为上面多了一排而往下跳。
  const mergeSeen = useRef(0);
  useLayoutEffect(() => {
    if (!feed.mergeShift || feed.mergeEpoch === mergeSeen.current) return;
    mergeSeen.current = feed.mergeEpoch;
    const { oldHeight, oldY } = feed.mergeShift;
    // 在最顶上时不需要补：新卡就该出现在眼前。
    if (oldY < 200) return;
    const grown = document.documentElement.scrollHeight - oldHeight;
    if (grown > 0) window.scrollTo({ top: oldY + grown });
  }, [feed.mergeEpoch, feed.mergeShift]);

  // AI 对话框把「它理解的条件」交给信息流：用事件而不是上下文，
  // 免得为一个筛选状态把整个 App 的 props 再穿一遍。
  useEffect(() => {
    const onFilter = (event: Event) => {
      const detail = (event as CustomEvent).detail as {
        platforms?: string[]; keyword?: string; range?: "today" | "all"; sort?: string;
      } | undefined;
      if (!detail) return;
      // 胶囊支持多选后，AI 给出的平台可以原样落进来（同一件事在几个平台上都有时更好对照）
      patch({
        platforms: Array.isArray(detail.platforms) ? detail.platforms : [],
        keyword: typeof detail.keyword === "string" ? detail.keyword : "",
        range: detail.range === "today" ? "today" : "all",
        ...(detail.sort ? { sort: detail.sort } : {}),
      });
    };
    window.addEventListener("onefeed:filter", onFilter);
    return () => window.removeEventListener("onefeed:filter", onFilter);
  }, []);

  useEffect(() => {
    document.title = ctx.summary?.total ? "OneFeed · " + ctx.summary.total + " 条" : "OneFeed";
  }, [ctx.summary?.total]);

  // 换排序或换筛选等于换了一屏内容，停在原来的滚动位置会莫名其妙。
  // 但从详情页返回时首帧要留在卡片原来的位置，别把它的落点滚走。
  const firstPaint = useRef(true);
  useEffect(() => {
    if (firstPaint.current) {
      firstPaint.current = false;
      return;
    }
    window.scrollTo({ top: 0 });
  }, [activeSort, selected.join(","), q, range, savedOnly]);

  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    for (const p of ctx.summary?.platforms ?? []) map[p.platform] = p.count;
    return map;
  }, [ctx.summary]);

  // 首启时后端会自动抓一轮；这时空态不能再叫人「点刷新」，否则两个提示互相打架。
  const refreshing = Boolean(ctx.progress?.running);

  const newest = useMemo(() => {
    const list = ctx.summary?.platforms ?? [];
    const ts = Math.max(0, ...list.map((p) => p.last_fetched_at));
    if (!ts) return "";
    const d = new Date(ts * 1000);
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  }, [ctx.summary]);

  // 底部给 AI 胶囊和渐隐层留出位置，最后一行卡片能滚到它上面
  return (
    <div className="pb-32">
      <section className="flex flex-wrap items-center gap-3 pt-6">
        <h1 className="font-display text-[15px] font-semibold tracking-tight">
          {savedOnly ? "我的收藏" : active ? "筛选结果" : range === "today" ? "今天" : "全部内容"}
        </h1>
        <Seg
          id="range"
          value={range}
          onChange={(next) => patch({ range: next })}
          options={[
            { id: "all" as const, label: "全部" },
            { id: "today" as const, label: "今天" },
          ]}
        />
        <Seg
          id="sort"
          value={activeSort as "freshness" | "engagement"}
          onChange={(next) => patch({ sort: next })}
          options={[
            { id: "freshness" as const, label: "按新鲜度" },
            { id: "engagement" as const, label: "按热度" },
          ]}
        />
        {/* 星标那份数据统一叫「稍后再看」（侧栏、右栏、卡片都是这个词）；
            这里是筛选入口，所以写「只看…」，跟旁边打开右栏的按钮区分开。 */}
        <button
          onClick={() => patch({ saved: !savedOnly })}
          aria-pressed={savedOnly}
          title={savedOnly ? "看全部内容" : "只看稍后再看的"}
          className={`flex items-center gap-1 rounded-full border px-3 py-1 text-[12px] transition ${
            savedOnly
              ? "border-ink bg-solid text-solid-fg"
              : "border-line text-muted hover:border-ink/25 hover:text-ink"
          }`}
        >
          <Star size={12} fill={savedOnly ? "currentColor" : "none"} />
          只看稍后再看
        </button>
        <ColsPicker
          choice={grid.choice}
          cols={grid.cols}
          maxFit={grid.maxFit}
          onChange={chooseCols}
        />
        <button
          onClick={() => window.dispatchEvent(new CustomEvent("onefeed:rail", { detail: { tab: "saved" } }))}
          title="打开右侧栏看稍后再看（]）"
          className="flex items-center gap-1 rounded-full border border-line px-3 py-1 text-[12px] text-muted transition hover:border-ink/25 hover:text-ink"
        >
          <Bookmark size={12} />
          稍后再看
        </button>
        <span className="ml-auto text-[12px] text-fade">
          {chipPlatforms ? chipPlatforms.length + " 个平台" : "加载中"}
          {newest ? " · 最近采集 " + newest : ""}
        </span>
      </section>

      <section className="mt-4">
        <Chips
          selected={selected}
          counts={counts}
          total={ctx.summary?.total ?? 0}
          platforms={chipPlatforms}
          onChange={(ids) => patch({ platforms: ids, keyword: "" })}
        />
      </section>

      {/* 进度不在这行里说了：顶栏刷新按钮左侧长出来的那件负责进度和结果，
          这里不再占一行高度，也不留空位。 */}

      {/* 人在列表深处时不拆屏：先给一个能点的落点，点了回顶再演 */}
      {pill !== null ? (
        <div className="fixed left-1/2 top-[84px] z-30 -translate-x-1/2">
          <button
            type="button"
            onClick={showNew}
            disabled={feed.loading}
            className="inline-flex h-8 items-center gap-1.5 rounded-full bg-ink px-3.5 text-[12px] text-paper shadow-card transition hover:opacity-90 disabled:opacity-60"
          >
            <ArrowUp size={12} />
            {feed.loading ? "正在取新内容…" : "有 " + pill + " 条新内容"}
          </button>
        </div>
      ) : null}

      {/* 换筛选后要立刻有动静：之前这一整屏到新数据回来之前一动不动，
          体感就是「点了没反应」，实测首帧要等 1 秒。 */}
      <p className="mt-4 min-h-[20px] text-[13px] leading-relaxed text-muted" aria-live="polite">
        {feed.loading && feed.items.length > 0
          ? "正在按新条件筛…"
          : feed.loading && feed.items.length === 0
          ? "正在取内容…"
          : active
            ? `筛选出 ${feed.items.length} 条，共 ${feed.count} 条命中`
            : ctx.summary?.text ?? ""}
      </p>

      {feed.error ? (
        // 只有一行红字等于「你自己想办法」：接口抖一下就得刷新整页。
        // 空态反而有两个动作，失败态一个都没有，这是反的。
        <div className="mt-6 flex flex-wrap items-center gap-3 rounded-card border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700">
          <span className="min-w-0 flex-1">{feed.error}</span>
          <button
            type="button"
            onClick={() => ctx.bump()}
            className="h-8 shrink-0 rounded-full border border-red-300/70 px-3 text-[12.5px] text-red-700 transition hover:bg-red-100"
          >
            重试
          </button>
        </div>
      ) : null}

      <LayoutGroup id="feed">
      <section
        ref={grid.ref}
        aria-busy={feed.loading || inShow}
        tabIndex={-1}
        style={{
          gridTemplateColumns: "repeat(" + grid.cols + ", minmax(0, 1fr))",
          // 收场时总高度会缩：锁住外层高度，页面下方才不被往上拽
          minHeight: lockHeight ? lockHeight + "px" : undefined,
        }}
        className={
          "mt-5 grid items-stretch gap-x-5 gap-y-5 transition-opacity duration-150 outline-none " +
          (feed.loading && feed.items.length > 0 && !inShow ? "opacity-55" : "opacity-100")
        }
      >
        {shownItems.map((item, index) => {
          // T5：换筛选 / 排序时让留下来的卡片滑到新位置。项数一多，逐张滑会像在拖地，
          // 所以只在 12 张以内开（正好是一屏的量），超过就直接换 —— 连 motion 节点都不建，
          // 免得 30 张卡各自挂一套布局测量。
          const isNew = Boolean(freshIds?.has(item.id));
          // waiting 也要算「收起态」：这时把 data-out 摘掉，刚收下去的旧卡会当场淡回来
          const out = phase === "collapsing" || phase === "waiting";
          const showing = phase === "revealing";
          // 逆序收：越靠后的卡越先走；cap 之后同一拍，别让 30 张排成 540ms 的长队
          const iVar = Math.max(0, REVEAL.cap - 1 - Math.min(index, REVEAL.cap - 1));
          const jVar = Math.min(index, REVEAL.cap);
          // 登场过的卡不再挂 .rise：不然演出结束那一刻、或者触底加载时会再淡一次
          const rise = !inShow && !isNew && !animatedIds.current.has(item.id) ? "rise" : "";
          const card = (
            <Card
              item={item}
              onOpen={openItem}
              reveal={isNew ? "new" : null}
              vtNames={
                item.id === backId && !backFromAgent ? { media: "of-media", title: "of-title" } : undefined
              }
            />
          );
          // 进场动画（.rise 用 animation-fill-mode: both，会永久压住 transform）
          // 必须挂在内层：挂在外层的话，FLIP 写进去的位移会被 CSS 动画覆盖成 0，
          // 换列时就只剩卡片瞬间换位、没有流动感。
          const style = {
            "--i": iVar,
            "--j": jVar,
            animationDelay: rise ? Math.min(index, 11) * 22 + "ms" : undefined,
          } as CSSProperties;
          return (
            <motion.div
              key={item.id}
              data-vt-item={item.id}
              layout={layoutOn && !inShow ? "position" : false}
              layoutDependency={grid.cols}
              transition={{ duration: DUR.base, ease: EASE }}
              className="h-full"
            >
              <div
                className={"feed-card relative h-full " + rise}
                data-out={out ? "1" : undefined}
                data-in={showing ? (isNew ? "new" : "carry") : undefined}
                data-new={isNew ? "1" : undefined}
                style={style}
              >
                {card}
              </div>
            </motion.div>
          );
        })}
      </section>
      </LayoutGroup>

      {feed.loading && feed.items.length === 0 ? (
        <div
          style={{ gridTemplateColumns: "repeat(" + grid.cols + ", minmax(0, 1fr))" }}
          className="mt-5 grid gap-x-5 gap-y-5"
        >
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="min-h-[340px] animate-pulse rounded-card border border-line bg-paper p-3">
              <div className="h-5 w-24 rounded bg-wash" />
              <div className="mt-2.5 aspect-video rounded-lg bg-wash" />
              <div className="mt-3 h-4 w-4/5 rounded bg-wash" />
              <div className="mt-2 h-4 w-3/5 rounded bg-wash" />
              <div className="mt-4 h-3 w-1/3 rounded bg-wash" />
            </div>
          ))}
        </div>
      ) : null}

      {!feed.loading && feed.items.length === 0 ? (
        <div className="mt-5 flex min-h-[420px] flex-col items-center justify-center text-center">
          <div className="text-[15px] font-medium">{savedOnly ? "还没有收藏" : "这里还没有内容"}</div>
          <p className="mt-2 text-[13px] text-muted">
            {savedOnly
              ? "跟底下的 AI 说「把这几条收藏起来」，或者点结果卡右边的星标。"
              : active
                ? "当前筛选下没有匹配，换个条件试试。"
                : refreshing
                  ? "正在抓取第一轮内容，抓完会自动出现在这里。"
                  : "第一次用的话，先登录、确认来源，再抓第一轮。"}
          </p>
          {savedOnly ? (
            <button
              onClick={() => patch({ saved: false })}
              className="mt-4 rounded-lg bg-solid px-4 py-2 text-[13px] text-solid-fg"
            >
              看全部内容
            </button>
          ) : refreshing ? (
            <span className="mt-4 flex items-center gap-2 rounded-lg bg-wash px-4 py-2 text-[13px] text-muted">
              <RefreshCw size={13} className="animate-spin" />
              正在抓取 {ctx.progress?.done ?? 0}/{ctx.progress?.total ?? 0}
            </span>
          ) : active ? (
            // 空态给的动作要和原因对上：筛选出 0 条时，刷新不会让结果出现，清条件才会
            <button
              onClick={() => patch({ platforms: [], keyword: "", range: "all", sort: "", saved: false })}
              className="mt-4 rounded-lg bg-solid px-4 py-2 text-[13px] text-solid-fg"
            >
              清空筛选条件
            </button>
          ) : (
            <>
              <ol className="mt-5 w-full max-w-[360px] space-y-2 text-left text-[12.5px] leading-relaxed text-muted">
                <li>
                  1.{" "}
                  <button type="button" onClick={() => navigate("/settings?section=auth")} className="text-ink underline decoration-line underline-offset-2 hover:decoration-ink">
                    去设置 · 登录态
                  </button>{" "}
                  登录小红书 / 抖音 / 知乎（B 站不用登录）
                </li>
                <li>
                  2.{" "}
                  <button type="button" onClick={() => navigate("/market")} className="text-ink underline decoration-line underline-offset-2 hover:decoration-ink">
                    到插件市场
                  </button>{" "}
                  确认要看的来源已经启用
                </li>
                <li>3. 回来点下面的「现在刷新一轮」</li>
              </ol>
              <button onClick={ctx.refresh} className="mt-4 rounded-lg bg-solid px-4 py-2 text-[13px] text-solid-fg">
                现在刷新一轮
              </button>
            </>
          )}
        </div>
      ) : null}

      {/* 触底状态条：高度固定 56px，翻页 / 自动检查 / 结果都在这一行换字，页面不抖。
          它一直存在（包括「已经到底了」），IntersectionObserver 才有落点。 */}
      {feed.items.length ? (
        <div
          ref={sentinel}
          aria-live="polite"
          data-auto-refresh={ctx.autoRunning ? "running" : "idle"}
          className="mt-8 flex min-h-[56px] flex-col items-center justify-center gap-1.5"
        >
          <motion.span
            key={feed.moreLoading ? "loading" : "idle"}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: DUR.micro, ease: EASE }}
            className="flex items-center gap-2 text-[12.5px] text-fade"
          >
            {ctx.autoRunning ? (
              <>
                <RefreshCw size={13} className="animate-spin text-accent" />
                正在看看有没有新内容
                {ctx.autoProgress && ctx.autoProgress.total
                  ? `… ${ctx.autoProgress.done}/${ctx.autoProgress.total}`
                  : "…"}
              </>
            ) : feed.merging ? (
              <>
                <Loader2 size={13} className="animate-spin" />
                正在把新内容放进来…
              </>
            ) : feed.moreLoading ? (
              <>
                <Loader2 size={13} className="animate-spin" />
                正在获取新内容…
              </>
            ) : feed.next ? (
              "继续往下滑，自动接着取"
            ) : ctx.autoResult?.error ? (
              `自动检查没成功：${ctx.autoResult.error}`
            ) : ctx.autoResult ? (
              <>
                自动检查完
                {ctx.autoResult.new_total > 0 ? `：新增 ${ctx.autoResult.new_total} 条` : "：这轮没有新内容"}
                {ctx.autoResult.failed ? ` · ${ctx.autoResult.failed} 个平台没抓到` : ""}
                {ctx.autoResult.cooling ? ` · ${ctx.autoResult.cooling} 个平台冷却中` : ""}
              </>
            ) : (
              "已经到底了"
            )}
          </motion.span>
          {!ctx.autoRunning && !feed.merging && !feed.next && ctx.autoResult?.error ? (
            <button
              onClick={() => ctx.autoRefresh(selected.length ? selected : undefined)}
              className="rounded-full border border-line px-2.5 py-1 text-[11.5px] text-muted transition hover:border-ink/25 hover:text-ink"
            >
              重试
            </button>
          ) : null}
          {ctx.autoRunning && ctx.autoProgress?.total ? (
            <span className="h-[3px] w-32 overflow-hidden rounded-full bg-wash">
              <span
                className="block h-full rounded-full bg-accent transition-[width] duration-500"
                style={{ width: Math.round((ctx.autoProgress.done / ctx.autoProgress.total) * 100) + "%" }}
              />
            </span>
          ) : null}
          {!ctx.autoRunning && !feed.next && (ctx.autoResult?.new_total ?? 0) > 0 ? (
            <button
              onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
              className="rounded-full border border-line px-2.5 py-1 text-[11.5px] text-muted transition hover:border-ink/25 hover:text-ink"
            >
              看看新增的 {ctx.autoResult?.new_total} 条
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** 分段控件：选中块用 layout 在两项之间滑过去，比瞬间换背景色顺 */
function Seg<T extends string>({
  id,
  value,
  options,
  onChange,
}: {
  id: string;
  value: T;
  options: { id: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="flex items-center gap-1 rounded-full border border-line p-0.5 text-[12px]">
      {options.map((o) => {
        const on = o.id === value;
        return (
          <button
            key={o.id}
            onClick={() => onChange(o.id)}
            aria-pressed={on}
            className={"relative rounded-full px-2.5 py-1 transition-colors " + (on ? "text-solid-fg" : "text-muted hover:text-ink")}
          >
            {on ? (
              <motion.span
                layoutId={"seg-" + id}
                className="absolute inset-0 rounded-full bg-solid"
                transition={{ type: "spring", stiffness: 560, damping: 40 }}
              />
            ) : null}
            <span className="relative">{o.label}</span>
          </button>
        );
      })}
    </div>
  );
}
