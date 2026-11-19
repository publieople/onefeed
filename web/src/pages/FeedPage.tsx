import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { LayoutGroup, motion, useReducedMotion } from "framer-motion";
import { Bookmark, Star } from "lucide-react";
import type { OutletCtx } from "../App";
import { useFeed, type FeedItem } from "../api";
import Card from "../components/Card";
import Chips from "../components/Chips";
import ColsPicker from "../components/ui/ColsPicker";
import { useGridCols, type ColsChoice } from "../layout/useGridCols";
import { runNav } from "../motion/nav";
import { DUR, EASE } from "../motion/tokens";
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
    const seek = () => find()?.scrollIntoView({ block: "center", behavior: "auto" });
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
    // 卡片里的媒体框和标题是共享元素的两端：给它们挂上名字，浏览器才知道这两块要「长大」
    const media = el?.querySelector<HTMLElement>('[data-vt="media"]') ?? null;
    const title = el?.querySelector<HTMLElement>('[data-vt="title"]') ?? null;
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
  const feed = useFeed(query, ctx.reloadKey);
  // 列数按网格实测宽度算（侧栏开合、窗口缩放都走这条），不再用 md:/xl: 视口断点
  const grid = useGridCols();
  const active = selected.length > 0 || q.trim().length > 0 || savedOnly;
  // 重排动画覆盖「换列数 / 侧栏开合 / 换筛选」三种情况。项数多时逐张滑太拖，
  // 所以 48 张封顶（一屏半的量），再多就直接换 —— 连 motion 节点都不建。
  // 系统里关掉动效的人，换列就直接到位。
  const reduceMotion = useReducedMotion();
  const animateLayout = feed.items.length > 0 && feed.items.length <= 48 && !reduceMotion;

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
    el.scrollIntoView({ block: "nearest" });
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
        <h1 className="text-[15px] font-medium">
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
        <button
          onClick={() => patch({ saved: !savedOnly })}
          aria-pressed={savedOnly}
          title={savedOnly ? "看全部内容" : "只看我收藏过的"}
          className={`flex items-center gap-1 rounded-full border px-3 py-1 text-[12px] transition ${
            savedOnly
              ? "border-ink bg-solid text-solid-fg"
              : "border-line text-muted hover:border-ink/25 hover:text-ink"
          }`}
        >
          <Star size={12} fill={savedOnly ? "currentColor" : "none"} />
          已收藏
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
          {ctx.summary ? ctx.summary.platforms.length + " 个平台" : "加载中"}
          {newest ? " · 最近采集 " + newest : ""}
        </span>
      </section>

      <section className="mt-4">
        <Chips
          selected={selected}
          counts={counts}
          total={ctx.summary?.total ?? 0}
          onChange={(ids) => patch({ platforms: ids, keyword: "" })}
        />
      </section>

      <p className="mt-4 min-h-[20px] text-[13px] leading-relaxed text-muted">
        {feed.loading && feed.items.length === 0
          ? "正在取内容…"
          : active
            ? `筛选出 ${feed.items.length} 条，共 ${feed.count} 条命中`
            : ctx.summary?.text ?? ""}
      </p>

      {feed.error ? (
        <div className="mt-6 rounded-card border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700">
          {feed.error}
        </div>
      ) : null}

      <LayoutGroup id="feed">
      <section
        ref={grid.ref}
        style={{ gridTemplateColumns: "repeat(" + grid.cols + ", minmax(0, 1fr))" }}
        className="mt-5 grid items-stretch gap-x-5 gap-y-5"
      >
        {feed.items.map((item, index) => {
          // T5：换筛选 / 排序时让留下来的卡片滑到新位置。项数一多，逐张滑会像在拖地，
          // 所以只在 12 张以内开（正好是一屏的量），超过就直接换 —— 连 motion 节点都不建，
          // 免得 30 张卡各自挂一套布局测量。
          const card = (
            <Card
              item={item}
              onOpen={openItem}
              vtNames={
                item.id === backId && !backFromAgent ? { media: "of-media", title: "of-title" } : undefined
              }
            />
          );
          // 进场动画（.rise 用 animation-fill-mode: both，会永久压住 transform）
          // 必须挂在内层：挂在外层的话，FLIP 写进去的位移会被 CSS 动画覆盖成 0，
          // 换列时就只剩卡片瞬间换位、没有流动感。
          const delay = { animationDelay: Math.min(index, 11) * 22 + "ms" };
          return animateLayout ? (
            <motion.div
              key={item.id}
              data-vt-item={item.id}
              layout="position"
              layoutDependency={grid.cols}
              transition={{ duration: DUR.base, ease: EASE }}
              className="h-full"
            >
              <div className="rise h-full" style={delay}>
                {card}
              </div>
            </motion.div>
          ) : (
            <div key={item.id} data-vt-item={item.id} className="rise h-full" style={delay}>
              {card}
            </div>
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
                : "点右上角刷新，或者先到插件市场装两个来源。"}
          </p>
          {savedOnly ? (
            <button
              onClick={() => patch({ saved: false })}
              className="mt-4 rounded-lg bg-solid px-4 py-2 text-[13px] text-solid-fg"
            >
              看全部内容
            </button>
          ) : active ? (
            // 空态给的动作要和原因对上：筛选出 0 条时，刷新不会让结果出现，清条件才会
            <button
              onClick={() => patch({ platforms: [], keyword: "", range: "all", sort: "", saved: false })}
              className="mt-4 rounded-lg bg-solid px-4 py-2 text-[13px] text-solid-fg"
            >
              清空筛选条件
            </button>
          ) : (
            <button onClick={ctx.refresh} className="mt-4 rounded-lg bg-solid px-4 py-2 text-[13px] text-solid-fg">
              现在刷新一轮
            </button>
          )}
        </div>
      ) : null}

      {feed.next ? (
        <div className="mt-10 flex justify-center">
          <button
            onClick={() => void feed.more()}
            disabled={feed.loading}
            className="rounded-full border border-line px-5 py-2 text-[13px] text-muted transition hover:border-ink/25 hover:text-ink disabled:opacity-50"
          >
            {feed.loading ? "加载中…" : "加载更多"}
          </button>
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
