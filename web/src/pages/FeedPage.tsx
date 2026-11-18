import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import type { OutletCtx } from "../App";
import { useFeed } from "../api";
import AiDock from "../components/AiDock";
import Card from "../components/Card";
import Chips from "../components/Chips";

interface Props {
  ctx: OutletCtx;
}

export default function FeedPage({ ctx }: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  const [sort, setSort] = useState("");
  const [range, setRange] = useState<"all" | "today">("all");
  const [q, setQ] = useState("");
  const navigate = useNavigate();
  const openItem = (id: string) => navigate("/item/" + encodeURIComponent(id));

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

  // AI 对话框把「它理解的条件」交给信息流：用事件而不是上下文，
  // 免得为一个筛选状态把整个 App 的 props 再穿一遍。
  useEffect(() => {
    const onFilter = (event: Event) => {
      const detail = (event as CustomEvent).detail as {
        platforms?: string[]; keyword?: string; range?: "today" | "all"; sort?: string;
      } | undefined;
      if (!detail) return;
      // 平台改成单选胶囊后只认第一个：AI 给出多个平台时先看第一个，其余在详情页对照
      setSelected(Array.isArray(detail.platforms) ? detail.platforms.slice(0, 1) : []);
      setQ(typeof detail.keyword === "string" ? detail.keyword : "");
      setRange(detail.range === "today" ? "today" : "all");
      if (detail.sort) setSort(detail.sort);
    };
    window.addEventListener("onefeed:filter", onFilter);
    return () => window.removeEventListener("onefeed:filter", onFilter);
  }, []);

  useEffect(() => {
    document.title = ctx.summary?.total ? "OneFeed · " + ctx.summary.total + " 条" : "OneFeed";
  }, [ctx.summary?.total]);

  // 换排序或换筛选等于换了一屏内容，停在原来的滚动位置会莫名其妙。
  useEffect(() => {
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
          onChange={setRange}
          options={[
            { id: "all" as const, label: "全部" },
            { id: "today" as const, label: "今天" },
          ]}
        />
        <Seg
          id="sort"
          value={activeSort as "freshness" | "engagement"}
          onChange={setSort}
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
          onChange={(id) => {
            setSelected(id ? [id] : []);
            setQ("");
          }}
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
          <div key={item.id} className="rise h-full" style={{ animationDelay: Math.min(index, 11) * 22 + "ms" }}>
            <Card item={item} onOpen={openItem} />
          </div>
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
            {selected.length || q
              ? "当前筛选下没有匹配，换个条件试试。"
              : "点右上角刷新，或者先到插件市场装两个来源。"}
          </p>
          <button onClick={ctx.refresh} className="mt-4 rounded-lg bg-solid px-4 py-2 text-[13px] text-solid-fg">
            现在刷新一轮
          </button>
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
