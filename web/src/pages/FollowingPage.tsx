import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  ChevronRight,
  Grid2X2,
  List,
  Loader2,
  RefreshCw,
  UserRound,
  X,
} from "lucide-react";
import type { OutletCtx } from "../App";
import {
  getJSON,
  postJSON,
  prefetchDetail,
  prefetchItem,
  putJSON,
  type FollowingItem,
  type FollowingLayout,
  type FollowingPlatform,
  type FollowingResponse,
  type RunState,
} from "../api";
import { num, timeAgo } from "../format";
import { platform } from "../platform";
import FollowingAccounts from "../components/FollowingAccounts";

const LAYOUTS: { id: FollowingLayout; label: string; icon: typeof List }[] = [
  { id: "list", label: "列表", icon: List },
  { id: "timeline", label: "时间线", icon: UserRound },
  { id: "compact", label: "紧凑", icon: Grid2X2 },
];

const STATE_LABEL: Record<string, string> = {
  ready: "",
  need_login: "需要登录",
  unsupported: "暂不支持",
  not_installed: "未安装",
};

function normalizeLayout(value?: string): FollowingLayout {
  return value === "timeline" || value === "compact" ? value : "list";
}

/** 平台原生关注流没有统一的发布时间：没有的时候按首次看到时间排，并明说「时间未知」。 */
function whenLabel(item: FollowingItem): string {
  if (item.time_estimated || !item.published_at) return "时间未知";
  return timeAgo(item.published_at);
}

function dayKey(item: FollowingItem): string {
  if (item.time_estimated || !item.published_at) return "unknown";
  const d = new Date(item.published_at * 1000);
  return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
}

function dayLabel(key: string): string {
  if (key === "unknown") return "时间未知";
  const now = new Date();
  const today = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
  const y = new Date(now.getTime() - 86400000);
  const yesterday = y.getFullYear() + "-" + String(y.getMonth() + 1).padStart(2, "0") + "-" + String(y.getDate()).padStart(2, "0");
  if (key === today) return "今天";
  if (key === yesterday) return "昨天";
  const [, m, d] = key.split("-");
  return Number(m) + " 月 " + Number(d) + " 日";
}

function tintOf(item: FollowingItem): string {
  return platform(item.platform).tint;
}

function KindIcon({ kind }: { kind: string }) {
  if (kind === "video") return <span className="text-[10px]">▶</span>;
  if (kind === "images") return <span className="text-[10px]">▧</span>;
  return <span className="text-[10px]">文</span>;
}

function Thumb({ item }: { item: FollowingItem }) {
  return (
    <span
      className="relative mt-0.5 h-[54px] w-[74px] shrink-0 overflow-hidden rounded-md bg-wash"
      style={{ background: tintOf(item) + "14" }}
    >
      <span className="absolute inset-0 flex items-center justify-center text-fade">
        <KindIcon kind={item.kind} />
      </span>
      {item.cover ? (
        <img
          src={item.cover}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          className="absolute inset-0 h-full w-full object-cover"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
      ) : null}
    </span>
  );
}

function Row({
  item,
  compact,
  showAuthor,
  onOpen,
}: {
  item: FollowingItem;
  compact?: boolean;
  showAuthor?: boolean;
  onOpen: (item: FollowingItem) => void;
}) {
  const p = platform(item.platform);
  const navigate = useNavigate();
  const location = useLocation();
  const goAuthor = (event: React.MouseEvent) => {
    if (!item.author_id) return;
    event.preventDefault();
    event.stopPropagation();
    navigate("/author/" + encodeURIComponent(item.platform) + "/" + encodeURIComponent(item.author_id), {
      state: { from: location.pathname + location.search },
    });
  };
  return (
    <a
      href={"/item/" + encodeURIComponent(item.id)}
      onClick={(e) => {
        // 保留 cmd/cmd+click 新开标签页的原生行为
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return;
        e.preventDefault();
        onOpen(item);
      }}
      onMouseEnter={() => prefetchItem(item.id)}
      className={
        "group flex gap-3 px-3 text-left transition hover:bg-wash/55 " +
        (compact ? "py-2.5" : "py-3.5")
      }
    >
      <Thumb item={item} />
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-1.5 text-[11px] text-fade">
          <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: p.tint }} />
          <span className="shrink-0">{p.label}</span>
          <span>·</span>
          <span className="shrink-0">{whenLabel(item)}</span>
          {showAuthor && item.author ? (
            <>
              <span>·</span>
              <span
                className={item.author_id ? "cursor-pointer truncate hover:text-ink" : "truncate"}
                onClick={goAuthor}
                title={item.author_id ? "看作者主页" : undefined}
              >
                {item.author}
              </span>
            </>
          ) : null}
        </span>
        <span
          className={
            "mt-0.5 block font-medium leading-snug text-ink " +
            (compact ? "line-clamp-2 text-[12.5px]" : "line-clamp-2 text-[13.5px]")
          }
        >
          {item.title}
        </span>
        {!compact && item.text ? (
          <span className="mt-1 line-clamp-2 block text-[12px] leading-relaxed text-muted">{item.text}</span>
        ) : null}
        <span className="mt-1 flex items-center gap-2.5 text-[11px] text-fade">
          {!showAuthor && item.author ? (
            <span
              className={"max-w-[45%] truncate " + (item.author_id ? "cursor-pointer hover:text-ink" : "")}
              onClick={goAuthor}
              title={item.author_id ? "看作者主页" : undefined}
            >
              @{item.author}
            </span>
          ) : null}
          {item.like_count ? <span>赞 {num(item.like_count)}</span> : null}
          {item.comment_count ? <span>评 {num(item.comment_count)}</span> : null}
          {item.saved ? <span className="text-accent">已收藏</span> : null}
        </span>
      </span>
      <ChevronRight size={14} className="mt-3 shrink-0 text-fade opacity-0 transition group-hover:opacity-100" />
    </a>
  );
}

export default function FollowingPage({ ctx }: { ctx: OutletCtx }) {
  useEffect(() => {
    document.title = "关注 · OneFeed";
  }, []);
  const navigate = useNavigate();
  const location = useLocation();

  // tab 要进 URL：从「关注的人」点进作者页再返回时，得回到名单而不是跌回动态。
  const [searchParams, setSearchParams] = useSearchParams();
  const tab: "feed" | "accounts" = searchParams.get("tab") === "accounts" ? "accounts" : "feed";
  const setTab = useCallback(
    (next: "feed" | "accounts") => {
      const params = new URLSearchParams(searchParams);
      if (next === "accounts") params.set("tab", "accounts");
      else params.delete("tab");
      setSearchParams(params, { replace: true });
    },
    [searchParams, setSearchParams],
  );
  const [data, setData] = useState<FollowingResponse | null>(null);
  const [items, setItems] = useState<FollowingItem[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [layout, setLayout] = useState<FollowingLayout>(() =>
    normalizeLayout(ctx.settings?.settings.following_layout),
  );
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [note, setNote] = useState("");
  const [progress, setProgress] = useState<RunState | null>(null);
  const [tick, setTick] = useState(0);
  const autoTried = useRef(false);
  const wasSyncing = useRef(false);

  // 设置页里改过的默认布局要能带过来；用户在本页临时切换后不回滚。
  useEffect(() => {
    setLayout(normalizeLayout(ctx.settings?.settings.following_layout));
  }, [ctx.settings?.settings.following_layout]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const params = new URLSearchParams({ limit: "30" });
    if (filter !== "all") params.set("platform", filter);
    getJSON<FollowingResponse>("/api/following?" + params.toString())
      .then((d) => {
        if (!alive) return;
        setData(d);
        setItems(d.items);
        setNext(d.next);
        setProgress(d.progress);
        if (d.progress?.running) wasSyncing.current = true;
        setNote("");
      })
      .catch((err: Error) => {
        if (alive) setNote(err.message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [filter, tick]);

  // 同步是后台线程：页面只轮询进度，跑完再重拉一页，不在主信息流上演出。
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const resp = await getJSON<{ state: RunState }>("/api/following/progress");
        if (!alive) return;
        const state = resp.state;
        setProgress(state);
        if (state.running) {
          wasSyncing.current = true;
        } else if (wasSyncing.current) {
          wasSyncing.current = false;
          setTick((n) => n + 1);
        }
      } catch {
        /* 进度接口偶尔读不到不影响已显示的内容 */
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  // 第一次打开且一条都没有：如果已经有平台登录，就自己同步一轮，别让用户对着一张空页发呆。
  useEffect(() => {
    if (!data || autoTried.current) return;
    if (data.syncing || data.total > 0) return;
    if (!data.platforms.some((p) => p.state === "ready")) return;
    autoTried.current = true;
    void postJSON<{ ok: boolean; state: RunState }>("/api/following/refresh", {})
      .then((resp) => {
        if (resp.ok) {
          setProgress(resp.state);
          wasSyncing.current = true;
        } else if (resp.state.error) {
          setNote(resp.state.error);
        }
      })
      .catch((err: Error) => setNote(err.message));
  }, [data]);

  const refresh = useCallback(
    async (force = false) => {
      setNote("");
      try {
        const resp = await postJSON<{ ok: boolean; state: RunState }>("/api/following/refresh", {
          platforms: filter === "all" ? undefined : [filter],
          force,
        });
        setProgress(resp.state);
        if (resp.ok) {
          wasSyncing.current = true;
        } else if (resp.state.error) {
          setNote(resp.state.error);
        }
      } catch (err) {
        setNote((err as Error).message);
      }
    },
    [filter],
  );

  const cancel = useCallback(async () => {
    try {
      await postJSON("/api/following/cancel", {});
      setProgress((prev) => (prev ? { ...prev, cancel_requested: true } : prev));
    } catch (err) {
      setNote((err as Error).message);
    }
  }, []);

  const loadMore = async () => {
    if (!next || loadingMore) return;
    setLoadingMore(true);
    const params = new URLSearchParams({ limit: "30", cursor: next });
    if (filter !== "all") params.set("platform", filter);
    try {
      const d = await getJSON<FollowingResponse>("/api/following?" + params.toString());
      setItems((prev) => {
        const seen = new Set(prev.map((i) => i.id));
        return prev.concat(d.items.filter((i) => !seen.has(i.id)));
      });
      setNext(d.next);
    } catch (err) {
      setNote((err as Error).message);
    } finally {
      setLoadingMore(false);
    }
  };

  const pickLayout = async (nextLayout: FollowingLayout) => {
    if (nextLayout === layout) return;
    const prev = layout;
    setLayout(nextLayout);
    try {
      await putJSON("/api/settings", { following_layout: nextLayout });
      await ctx.reloadSettings();
    } catch (err) {
      setLayout(prev);
      setNote((err as Error).message);
    }
  };

  const open = (item: FollowingItem) => {
    prefetchDetail(item.id);
    navigate("/item/" + encodeURIComponent(item.id), {
      state: {
        from: "/following" + location.search,
        fromId: item.id,
        item,
      },
    });
    window.scrollTo(0, 0);
  };

  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    for (const c of data?.counts ?? []) map[c.platform] = c.count;
    return map;
  }, [data?.counts]);

  const dateGroups = useMemo(() => {
    const map = new Map<string, FollowingItem[]>();
    for (const item of items) {
      const key = dayKey(item);
      const list = map.get(key) ?? [];
      list.push(item);
      map.set(key, list);
    }
    const groups = Array.from(map.entries());
    // 有日期的按天倒序；「时间未知」放最后，别让小红书的估时条目一上来就霸屏
    return groups.sort((a, b) => {
      if (a[0] === "unknown") return 1;
      if (b[0] === "unknown") return -1;
      return b[0].localeCompare(a[0]);
    });
  }, [items]);

  const authorGroups = useMemo(() => {
    const map = new Map<string, { name: string; avatar: string; items: FollowingItem[] }>();
    for (const item of items) {
      const key = item.author_id || item.author || "unknown";
      const row = map.get(key) ?? { name: item.author || "未知作者", avatar: item.author_avatar || "", items: [] };
      row.items.push(item);
      map.set(key, row);
    }
    const groups = Array.from(map.entries());
    // 时间线按「这个作者最近一条有时间的帖子」倒序；只有估时条目的作者排最后
    return groups.sort((a, b) => {
      const aKnown = a[1].items.some((i) => Boolean(i.published_at));
      const bKnown = b[1].items.some((i) => Boolean(i.published_at));
      if (aKnown !== bKnown) return aKnown ? -1 : 1;
      const aLatest = Math.max(0, ...a[1].items.map((i) => i.published_at || 0));
      const bLatest = Math.max(0, ...b[1].items.map((i) => i.published_at || 0));
      if (aLatest !== bLatest) return bLatest - aLatest;
      return b[1].items.length - a[1].items.length;
    });
  }, [items]);

  const running = Boolean(progress?.running);
  const runningRow = Object.entries(progress?.plugins ?? {}).find(([, p]) => p.status === "running");
  const runningLabel = runningRow ? runningRow[1].label || runningRow[0] : "";
  const done = progress?.done ?? 0;
  const total = progress?.total ?? 0;
  const issues = (data?.platforms ?? []).filter((p: FollowingPlatform) => p.state !== "ready");
  const ready = (data?.platforms ?? []).filter((p) => p.state === "ready");
  const lastSync = (data?.platforms ?? []).reduce((max, p) => Math.max(max, p.last_sync_at || 0), 0);

  return (
    <div className="pb-28 pt-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="font-display text-[22px] font-semibold tracking-tight">关注</h1>
          <p className="mt-1 text-[12px] text-muted">
            {tab === "feed" ? (
              <>
                你关注的人发了什么 · 平台原生关注流，不混推荐
                {data ? <span className="ml-2 text-fade">共 {data.total} 条</span> : null}
                {lastSync ? <span className="ml-2 text-fade">· 上次同步 {timeAgo(lastSync)}</span> : null}
              </>
            ) : (
              <>你关注了谁 · 只同步你本人账号的名单，不是推荐关注</>
            )}
          </p>
        </div>
        <div className={"flex items-center gap-2" + (tab === "accounts" ? " invisible" : "")}>
          {running ? (
            <div
              className="flex h-9 items-center gap-2 rounded-full border border-line bg-wash/60 pl-3 pr-1 text-[12px]"
              aria-live="polite"
            >
              <Loader2 size={13} className="animate-spin text-accent" />
              <span className="text-ink">正在同步</span>
              {runningLabel ? <span className="text-muted">{runningLabel}</span> : null}
              <span className="tabular-nums text-muted">{done}/{total}</span>
              <button
                onClick={() => void cancel()}
                title="停止这一轮同步"
                aria-label="停止这一轮同步"
                className="ml-1 flex h-7 w-7 items-center justify-center rounded-full text-muted transition hover:bg-wash hover:text-ink"
              >
                <X size={13} />
              </button>
            </div>
          ) : null}
          <button
            onClick={() => void refresh(false)}
            disabled={running}
            className="flex h-9 items-center gap-1.5 rounded-lg bg-solid px-3.5 text-[13px] font-medium text-solid-fg transition disabled:opacity-45"
          >
            <RefreshCw size={14} className={running ? "animate-spin" : ""} />
            同步关注
          </button>
        </div>
      </header>

      <div className="mt-4 inline-flex items-center rounded-full border border-line bg-wash/40 p-0.5" role="tablist" aria-label="关注页视图">
        {([["feed", "动态"], ["accounts", "关注的人"]] as const).map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={
              "h-7 rounded-full px-3 text-[12px] transition " +
              (tab === id ? "bg-paper text-ink shadow-sm" : "text-muted hover:text-ink")
            }
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "feed" ? (
        <>
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <button
          onClick={() => setFilter("all")}
          className={
            "flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12px] transition " +
            (filter === "all" ? "border-ink/25 bg-paper text-ink shadow-sm" : "border-line text-muted hover:text-ink")
          }
        >
          全部
          <span className="tabular-nums text-fade">{data?.total ?? 0}</span>
        </button>
        {(data?.platforms ?? []).map((p) => {
          const disabled = p.state === "not_installed" || p.state === "unsupported";
          const active = filter === p.platform;
          return (
            <button
              key={p.platform}
              onClick={() => {
                if (disabled) return;
                setFilter(p.platform);
                if (p.state === "need_login") setNote(p.note || "这个平台需要登录");
                else setNote("");
              }}
              disabled={disabled}
              title={p.note || p.label}
              className={
                "flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12px] transition " +
                (active ? "border-ink/25 bg-paper text-ink shadow-sm" : "border-line text-muted hover:text-ink") +
                (disabled ? " cursor-not-allowed opacity-45" : "")
              }
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: platform(p.platform).tint }} />
              {p.label}
              {counts[p.platform] ? <span className="tabular-nums text-fade">{counts[p.platform]}</span> : null}
              {p.state === "need_login" ? <AlertTriangle size={11} className="text-amber-500" /> : null}
            </button>
          );
        })}
        <div className="ml-auto flex items-center rounded-full border border-line bg-wash/40 p-0.5" role="group" aria-label="关注页布局">
          {LAYOUTS.map((l) => {
            const Icon = l.icon;
            return (
              <button
                key={l.id}
                onClick={() => void pickLayout(l.id)}
                title={"切换成" + l.label + "布局"}
                aria-label={"切换成" + l.label + "布局"}
                aria-pressed={layout === l.id}
                className={
                  "flex h-7 items-center gap-1 rounded-full px-2.5 text-[11px] transition " +
                  (layout === l.id ? "bg-paper text-ink shadow-sm" : "text-muted hover:text-ink")
                }
              >
                <Icon size={12} />
                {l.label}
              </button>
            );
          })}
        </div>
      </div>

      {note ? <p className="mt-3 text-[12px] text-danger">{note}</p> : null}

      {issues.length ? (
        <div className="mt-3 flex flex-wrap items-start gap-x-4 gap-y-1 rounded-lg border border-line bg-wash/35 px-3 py-2 text-[11px] text-muted">
          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber-500" />
          {issues.map((p) => (
            <span key={p.platform} className="leading-relaxed">
              <span className="font-medium text-ink">{p.label}</span>
              {STATE_LABEL[p.state] ? "：" + STATE_LABEL[p.state] : ""}
              {p.note ? " · " + p.note : ""}
            </span>
          ))}
        </div>
      ) : null}

      {data?.plugin_errors?.length ? (
        <p className="mt-2 text-[11px] text-danger">{data.plugin_errors.join("；")}</p>
      ) : null}

      {loading ? (
        <div className="mt-6 space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex gap-3 rounded-xl border border-line bg-paper p-3">
              <div className="h-[54px] w-[74px] animate-pulse rounded-md bg-wash" />
              <div className="flex-1 space-y-2 py-1">
                <div className="h-3 w-28 animate-pulse rounded bg-wash" />
                <div className="h-4 w-4/5 animate-pulse rounded bg-wash" />
              </div>
            </div>
          ))}
        </div>
      ) : items.length === 0 ? (
        <div className="mt-8 rounded-xl border border-line bg-paper px-5 py-10 text-center">
          <p className="text-[14px] font-medium text-ink">
            {running ? "正在同步你关注的人…" : filter === "all" ? "关注流还没有内容" : "这个平台还没有关注流内容"}
          </p>
          <p className="mx-auto mt-1.5 max-w-[440px] text-[12px] leading-relaxed text-muted">
            {ready.length
              ? "点「同步关注」去平台上抓一轮；抓不到会在这里说清楚原因，不会拿推荐流冒充。"
              : "先在上面的状态里把平台装好、登录好，再回来同步。"}
          </p>
          <button
            onClick={() => void refresh(false)}
            disabled={running}
            className="mt-4 inline-flex h-9 items-center gap-1.5 rounded-lg border border-line px-3.5 text-[13px] text-ink transition hover:bg-wash disabled:opacity-45"
          >
            <RefreshCw size={14} />
            {running ? "正在同步…" : "同步关注"}
          </button>
        </div>
      ) : layout === "timeline" ? (
        <div className="mt-5 space-y-5">
          {authorGroups.map(([key, group]) => (
            <section key={key}>
              <div className="flex items-center gap-2 px-1">
                {group.avatar ? (
                  <img
                    src={group.avatar}
                    alt=""
                    loading="lazy"
                    referrerPolicy="no-referrer"
                    className="h-7 w-7 rounded-full object-cover"
                    onError={(e) => {
                      (e.currentTarget as HTMLImageElement).style.display = "none";
                    }}
                  />
                ) : (
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-wash text-[11px] text-muted">
                    {group.name.slice(0, 1)}
                  </span>
                )}
                <span
                  className={
                    "text-[13px] font-medium text-ink " +
                    (group.items[0]?.author_id ? "cursor-pointer rounded hover:opacity-75" : "")
                  }
                  onClick={() => {
                    const first = group.items[0];
                    if (!first?.author_id) return;
                    navigate(
                      "/author/" + encodeURIComponent(first.platform) + "/" + encodeURIComponent(first.author_id),
                      { state: { from: location.pathname + location.search } },
                    );
                  }}
                  title={group.items[0]?.author_id ? "看作者主页" : undefined}
                >
                  {group.name}
                </span>
                <span className="text-[11px] text-fade">{group.items.length} 条</span>
              </div>
              <div className="mt-2 divide-y divide-line/60 rounded-xl border border-line bg-paper">
                {group.items.map((item) => (
                  <Row key={item.id} item={item} compact onOpen={open} />
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className="mt-5 space-y-5">
          {dateGroups.map(([key, group]) => (
            <section key={key}>
              <div className="flex items-baseline gap-2 px-1">
                <h2 className="text-[12px] font-medium text-muted">{dayLabel(key)}</h2>
                <span className="text-[11px] text-fade">{group.length} 条</span>
                {key === "unknown" ? (
                  <span className="text-[11px] text-fade">平台没给发布时间，按第一次看到的时间排</span>
                ) : null}
              </div>
              <div
                className={
                  "mt-2 overflow-hidden rounded-xl border border-line bg-paper " +
                  (layout === "compact" ? "grid sm:grid-cols-2" : "divide-y divide-line/60")
                }
              >
                {group.map((item) => (
                  <div key={item.id} className={layout === "compact" ? "border-b border-line/60 last:border-b-0 sm:odd:border-r" : ""}>
                    <Row item={item} compact={layout === "compact"} onOpen={open} />
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {next ? (
        <div className="mt-6 flex justify-center">
          <button
            onClick={() => void loadMore()}
            disabled={loadingMore}
            className="h-9 rounded-lg border border-line px-4 text-[13px] text-muted transition hover:text-ink disabled:opacity-50"
          >
            {loadingMore ? "加载中…" : "加载更多"}
          </button>
        </div>
      ) : items.length ? (
        <p className="mt-6 text-center text-[11px] text-fade">这一页到底了</p>
      ) : null}
        </>
      ) : (
        <FollowingAccounts />
      )}
    </div>
  );
}
