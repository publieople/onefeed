import { useEffect, useMemo, useState } from "react";
import type { OutletCtx } from "../App";
import { useFeed } from "../api";
import Card from "../components/Card";
import Chips from "../components/Chips";
import Drawer from "../components/Drawer";
import FilterBox from "../components/FilterBox";
import { platform } from "../platform";

interface Props {
  ctx: OutletCtx;
}

export default function FeedPage({ ctx }: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  const [sort, setSort] = useState("freshness");
  const [q, setQ] = useState("");
  const [drawer, setDrawer] = useState<string | null>(null);

  const query = useMemo(() => ({ platforms: selected, kind: "", sort, q }), [selected, sort, q]);
  const feed = useFeed(query, ctx.reloadKey);
  const active = selected.length > 0 || q.trim().length > 0;

  useEffect(() => {
    document.title = ctx.summary?.total ? "OneFeed · " + ctx.summary.total + " 条" : "OneFeed";
  }, [ctx.summary?.total]);

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

  const toggle = (id: string) => {
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
    setQ("");
  };

  return (
    <div className="pb-24">
      <section className="flex items-center gap-3 pt-6">
        <h1 className="text-[15px] font-medium">{active ? "筛选结果" : "全部时间"}</h1>
        <div className="flex items-center gap-1 rounded-full border border-line p-0.5 text-[12px]">
          {[
            { id: "freshness", label: "按新鲜度" },
            { id: "engagement", label: "按热度" },
          ].map((s) => (
            <button
              key={s.id}
              onClick={() => setSort(s.id)}
              className={
                "rounded-full px-2.5 py-1 transition " +
                (sort === s.id ? "bg-ink text-white" : "text-muted hover:text-ink")
              }
            >
              {s.label}
            </button>
          ))}
        </div>
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
          onToggle={toggle}
          onClear={() => {
            setSelected([]);
            setQ("");
          }}
        />
      </section>

      <FilterBox value={q} parsed={feed.parsed} onSubmit={setQ} />

      {!feed.loading ? (
        <p className="mt-4 text-[12.5px] leading-relaxed text-muted">
          {active
            ? `筛选出 ${feed.items.length} 条，共 ${feed.count} 条命中`
            : ctx.summary?.text ?? ""}
        </p>
      ) : null}

      {feed.error ? (
        <div className="mt-6 rounded-card border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700">
          {feed.error}
        </div>
      ) : null}

      <section className="mt-5 grid grid-cols-1 items-start gap-x-5 gap-y-8 md:grid-cols-2 xl:grid-cols-3">
        {feed.items.map((item) => (
          <Card key={item.id} item={item} onOpen={setDrawer} />
        ))}
      </section>

      {feed.loading && feed.items.length === 0 ? (
        <div className="mt-10 grid grid-cols-1 gap-x-5 gap-y-8 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="animate-pulse">
              <div className="aspect-video rounded-card bg-wash" />
              <div className="mt-3 h-4 w-4/5 rounded bg-wash" />
              <div className="mt-2 h-3 w-1/3 rounded bg-wash" />
            </div>
          ))}
        </div>
      ) : null}

      {!feed.loading && feed.items.length === 0 ? (
        <div className="mt-16 text-center">
          <div className="text-[15px] font-medium">这里还没有内容</div>
          <p className="mt-2 text-[13px] text-muted">
            {selected.length || q
              ? "当前筛选下没有匹配，换个条件试试。"
              : "点右上角刷新，或者先到插件市场装两个来源。"}
          </p>
          <button onClick={ctx.refresh} className="mt-4 rounded-lg bg-ink px-4 py-2 text-[13px] text-white">
            刷新六个平台
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

      {selected.length === 1 ? (
        <div className="mt-8 text-center text-[12px] text-fade">
          正在看 {platform(selected[0]).label}，再点一个平台可以并排比较
        </div>
      ) : null}

      <Drawer id={drawer} onClose={() => setDrawer(null)} />
    </div>
  );
}
