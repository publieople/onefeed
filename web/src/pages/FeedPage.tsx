import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import type { OutletCtx } from "../App";
import { useFeed, type FeedItem } from "../api";
import AiDock from "../components/AiDock";
import Card from "../components/Card";
import Chips from "../components/Chips";
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
  const patch = (next: {
    platforms?: string[];
    keyword?: string;
    sort?: string;
    range?: "all" | "today";
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
    setParams(sp, { replace: true });
  };
  const navigate = useNavigate();
  const location = useLocation();
  // 从详情页返回时，详情页要缩回这张卡片：它得先在场，还要在视野里
  const backId = (location.state as { fromId?: string } | null)?.fromId ?? null;
  const restoreAnchor = (): (() => void) | undefined => {
    if (!backId) return;
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
  const openItem = (id: string, el?: HTMLElement, seed?: FeedItem) => {
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
  };

  const activeSort = sort || ctx.settings?.settings.default_sort || "freshness";
  const since = useMemo(() => {
    if (range !== "today") return null;
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return Math.floor(d.getTime() / 1000);
  }, [range]);
  const query = useMemo(
    () => ({ platforms: selected, kind: "", sort: activeSort, q, since }),
    [selected, activeSort, q, since],
  );
  const feed = useFeed(query, ctx.reloadKey);
  const active = selected.length > 0 || q.trim().length > 0;
  // 重排动画只在「一屏装得下」时开：项数多的时候逐张滑会拖成一条虫
  const animateLayout = feed.items.length > 0 && feed.items.length <= 12;

  // ── 列表键盘模型：j/k 上下、h/l 跨列、o 新标签打开、Enter 交给原生 <a>
  const [cursor, setCursor] = useState(-1);
  const cardEls = () => Array.from(document.querySelectorAll<HTMLAnchorElement>('[data-vt-item] a[href^="/item/"]'));
  const cols = () => (window.innerWidth >= 1280 ? 3 : window.innerWidth >= 768 ? 2 : 1);
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
    l: () => moveCursor(cols()),
    h: () => moveCursor(-cols()),
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
  }, [activeSort, selected.join(","), q, range]);

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

  return (
    <div className="pb-24">
      <section className="flex flex-wrap items-center gap-3 pt-6">
        <h1 className="text-[15px] font-medium">{active ? "筛选结果" : range === "today" ? "今天" : "全部内容"}</h1>
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

      <section className="mt-5 grid grid-cols-1 items-stretch gap-x-5 gap-y-5 md:grid-cols-2 xl:grid-cols-3">
        {feed.items.map((item, index) => (
          // T5：换筛选 / 排序时让留下来的卡片滑到新位置。项数一多，逐张滑会像在拖地，
          // 所以只在 12 张以内开（正好是一屏的量），超过就直接换。
          <motion.div
            key={item.id}
            data-vt-item={item.id}
            layout={animateLayout ? "position" : false}
            transition={{ duration: DUR.base, ease: EASE }}
            className="rise h-full"
            style={{ animationDelay: Math.min(index, 11) * 22 + "ms" }}
          >
            <Card
              item={item}
              onOpen={openItem}
              vtNames={
                item.id === backId ? { media: "of-media", title: "of-title" } : undefined
              }
            />
          </motion.div>
        ))}
      </section>

      {feed.loading && feed.items.length === 0 ? (
        <div className="mt-5 grid grid-cols-1 gap-x-5 gap-y-5 md:grid-cols-2 xl:grid-cols-3">
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
          <div className="text-[15px] font-medium">这里还没有内容</div>
          <p className="mt-2 text-[13px] text-muted">
            {active ? "当前筛选下没有匹配，换个条件试试。" : "点右上角刷新，或者先到插件市场装两个来源。"}
          </p>
          {active ? (
            // 空态给的动作要和原因对上：筛选出 0 条时，刷新不会让结果出现，清条件才会
            <button
              onClick={() => patch({ platforms: [], keyword: "", range: "all", sort: "" })}
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

      <AiDock onOpenItem={openItem} />
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
