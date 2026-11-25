import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { AlertTriangle, Info, Loader2, RefreshCw, Search, UserRound, X } from "lucide-react";
import {
  getJSON,
  postJSON,
  type FollowingAccount,
  type FollowingAccountsResponse,
  type FollowingPlatform,
  type RunState,
} from "../api";
import { timeAgo } from "../format";
import { platform } from "../platform";

const STATE_LABEL: Record<string, string> = {
  ready: "",
  need_login: "需要登录",
  unsupported: "暂不支持名单",
  not_installed: "未安装",
};

function accountName(a: FollowingAccount): string {
  return a.name || "未命名账号";
}

function AccountRow({ account, from }: { account: FollowingAccount; from: string }) {
  const p = platform(account.platform);
  return (
    <Link
      to={"/author/" + encodeURIComponent(account.platform) + "/" + encodeURIComponent(account.account_id)}
      state={{ from }}
      className="group flex items-center gap-3 px-3.5 py-3 transition hover:bg-wash/55"
    >
      {account.avatar ? (
        <img
          src={account.avatar}
          alt=""
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          className="h-9 w-9 shrink-0 rounded-full object-cover"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).style.display = "none";
          }}
        />
      ) : (
        <span
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[12px] font-medium text-white"
          style={{ background: p.tint }}
        >
          {accountName(account).slice(0, 1)}
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate text-[13.5px] font-medium text-ink">{accountName(account)}</span>
          <span className="h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: p.tint }} />
          <span className="shrink-0 text-[11px] text-fade">{p.label}</span>
        </span>
        <span className="mt-0.5 line-clamp-2 block text-[12px] leading-relaxed text-muted">
          {account.bio || "没写简介"}
        </span>
        <span className="mt-1 flex items-center gap-2 text-[11px] text-fade">
          {account.last_seen_at ? <span>最近见到 {timeAgo(account.last_seen_at)}</span> : null}
          {account.relation ? <span>· {account.relation === "following" ? "关注中" : account.relation}</span> : null}
        </span>
      </span>
      <span className="shrink-0 text-[11px] text-fade opacity-0 transition group-hover:opacity-100">
        看主页
      </span>
    </Link>
  );
}

export default function FollowingAccounts() {
  const location = useLocation();
  const [data, setData] = useState<FollowingAccountsResponse | null>(null);
  const [accounts, setAccounts] = useState<FollowingAccount[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [platformFilter, setPlatformFilter] = useState("all");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [note, setNote] = useState("");
  const [progress, setProgress] = useState<RunState | null>(null);
  const [tick, setTick] = useState(0);
  const autoTried = useRef(false);
  const wasSyncing = useRef(false);

  const fetchPage = useCallback(
    async (offset: number) => {
      const params = new URLSearchParams({ limit: "100", offset: String(offset) });
      if (platformFilter !== "all") params.set("platform", platformFilter);
      if (q.trim()) params.set("q", q.trim());
      return getJSON<FollowingAccountsResponse>("/api/following/accounts?" + params.toString());
    },
    [platformFilter, q],
  );

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetchPage(0)
      .then((d) => {
        if (!alive) return;
        setData(d);
        setAccounts(d.accounts);
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
  }, [fetchPage, tick]);

  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const resp = await getJSON<{ state: RunState }>("/api/following/accounts/progress");
        if (!alive) return;
        setProgress(resp.state);
        if (resp.state.running) {
          wasSyncing.current = true;
        } else if (wasSyncing.current) {
          wasSyncing.current = false;
          setTick((n) => n + 1);
        }
      } catch {
        /* 名单同步进度读不到时，保留已经显示的名单 */
      }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const ready = (data?.platforms ?? []).filter((p) => p.state === "ready");
  const supported = (data?.platforms ?? []).filter((p) => p.supported);
  const issues = (data?.platforms ?? []).filter((p: FollowingPlatform) => p.state !== "ready" && p.state !== "not_installed");
  const unsupported = issues.filter((p) => p.state === "unsupported");
  const problems = issues.filter((p) => p.state !== "unsupported");

  const sync = async (force = false) => {
    setNote("");
    try {
      const resp = await postJSON<{ ok: boolean; state: RunState }>("/api/following/accounts/refresh", {
        platforms: platformFilter === "all" ? undefined : [platformFilter],
        force,
      });
      setProgress(resp.state);
      if (resp.ok) wasSyncing.current = true;
      else if (resp.state.error) setNote(resp.state.error);
    } catch (err) {
      setNote((err as Error).message);
    }
  };

  useEffect(() => {
    if (!data || autoTried.current) return;
    if (data.syncing || data.total > 0 || ready.length === 0) return;
    autoTried.current = true;
    void sync(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);

  const cancel = async () => {
    try {
      await postJSON("/api/following/accounts/cancel", {});
      setProgress((prev) => (prev ? { ...prev, cancel_requested: true } : prev));
    } catch (err) {
      setNote((err as Error).message);
    }
  };

  const loadMore = async () => {
    if (next == null || loadingMore) return;
    setLoadingMore(true);
    try {
      const d = await fetchPage(next);
      setAccounts((prev) => {
        const seen = new Set(prev.map((a) => a.platform + ":" + a.account_id));
        return prev.concat(d.accounts.filter((a) => !seen.has(a.platform + ":" + a.account_id)));
      });
      setNext(d.next);
    } catch (err) {
      setNote((err as Error).message);
    } finally {
      setLoadingMore(false);
    }
  };

  const running = Boolean(progress?.running);
  const runningRow = Object.entries(progress?.plugins ?? {}).find(([, p]) => p.status === "running");
  const runningLabel = runningRow ? runningRow[1].label || runningRow[0] : "";
  const done = progress?.done ?? 0;
  const total = progress?.total ?? 0;
  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    for (const c of data?.counts ?? []) map[c.platform] = c.count;
    return map;
  }, [data?.counts]);
  const from = location.pathname + location.search;

  return (
    <div className="pb-24">
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <button
          onClick={() => setPlatformFilter("all")}
          className={
            "flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12px] transition " +
            (platformFilter === "all" ? "border-ink/25 bg-paper text-ink shadow-sm" : "border-line text-muted hover:text-ink")
          }
        >
          全部
          <span className="tabular-nums text-fade">{data?.total ?? 0}</span>
        </button>
        {supported.map((p) => {
          const active = platformFilter === p.platform;
          return (
            <button
              key={p.platform}
              onClick={() => setPlatformFilter(p.platform)}
              title={p.note || p.label}
              className={
                "flex h-8 items-center gap-1.5 rounded-full border px-3 text-[12px] transition " +
                (active ? "border-ink/25 bg-paper text-ink shadow-sm" : "border-line text-muted hover:text-ink")
              }
            >
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: platform(p.platform).tint }} />
              {p.label}
              {counts[p.platform] ? <span className="tabular-nums text-fade">{counts[p.platform]}</span> : null}
            </button>
          );
        })}
        <div className="relative ml-auto">
          <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fade" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜名字或简介"
            aria-label="搜关注的人"
            className="h-8 w-[180px] rounded-full border border-line bg-transparent pl-7 pr-7 text-[12px] text-ink outline-none placeholder:text-fade focus:border-ink/30"
          />
          {q ? (
            <button
              onClick={() => setQ("")}
              aria-label="清空搜索"
              className="absolute right-1.5 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full text-fade hover:text-ink"
            >
              <X size={12} />
            </button>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {running ? (
            <div
              className="flex h-8 items-center gap-1.5 rounded-full border border-line bg-wash/60 pl-2.5 pr-1 text-[11px]"
              aria-live="polite"
            >
              <Loader2 size={12} className="animate-spin text-accent" />
              <span>正在同步名单</span>
              {runningLabel ? <span className="text-muted">{runningLabel}</span> : null}
              <span className="tabular-nums text-muted">{done}/{total}</span>
              <button
                onClick={() => void cancel()}
                title="停止这一轮名单同步"
                aria-label="停止这一轮名单同步"
                className="ml-0.5 flex h-6 w-6 items-center justify-center rounded-full text-muted hover:bg-wash hover:text-ink"
              >
                <X size={12} />
              </button>
            </div>
          ) : null}
          <button
            onClick={() => void sync(false)}
            disabled={running}
            className="flex h-8 items-center gap-1.5 rounded-full border border-line px-3 text-[12px] text-ink transition hover:bg-wash disabled:opacity-45"
          >
            <RefreshCw size={13} className={running ? "animate-spin" : ""} />
            同步名单
          </button>
        </div>
      </div>

      {note ? <p className="mt-3 text-[12px] text-danger">{note}</p> : null}

      {unsupported.length ? (
        <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-relaxed text-muted">
          <Info size={13} className="mt-0.5 shrink-0 text-fade" />
          <span>
            {unsupported.map((p) => p.label).join("、")}
            的插件还没有关注名单能力，这里只列有名单能力的平台；它们的内容仍会照常出现在关注动态里。
          </span>
        </p>
      ) : null}

      {problems.length ? (
        <div className="mt-3 flex flex-wrap items-start gap-x-4 gap-y-1 rounded-lg border border-line bg-wash/35 px-3 py-2 text-[11px] text-muted">
          <AlertTriangle size={13} className="mt-0.5 shrink-0 text-amber-500" />
          {problems.map((p) => (
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
        <div className="mt-5 space-y-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="flex items-center gap-3 rounded-xl border border-line bg-paper p-3">
              <div className="h-9 w-9 animate-pulse rounded-full bg-wash" />
              <div className="flex-1 space-y-2">
                <div className="h-3 w-28 animate-pulse rounded bg-wash" />
                <div className="h-3 w-3/5 animate-pulse rounded bg-wash" />
              </div>
            </div>
          ))}
        </div>
      ) : accounts.length === 0 ? (
        <div className="mt-7 rounded-xl border border-line bg-paper px-5 py-10 text-center">
          <UserRound size={22} className="mx-auto text-fade" />
          <p className="mt-2 text-[14px] font-medium text-ink">
            {q ? "没搜到这个人" : "还没有关注名单"}
          </p>
          <p className="mx-auto mt-1.5 max-w-[460px] text-[12px] leading-relaxed text-muted">
            {q
              ? "换个名字试试；名单只同步你本人账号关注的人，不是推荐关注。"
              : ready.length
                ? "点「同步名单」去平台拉一次。拿不到时会说清楚是没登录、插件没装，还是平台不给。"
                : "先把平台装好并登录，再回来同步名单。"}
          </p>
        </div>
      ) : (
        <div className="mt-5 overflow-hidden rounded-xl border border-line bg-paper">
          <div className="divide-y divide-line/60">
            {accounts.map((a) => (
              <AccountRow key={a.platform + ":" + a.account_id} account={a} from={from} />
            ))}
          </div>
        </div>
      )}

      {next != null ? (
        <div className="mt-6 flex justify-center">
          <button
            onClick={() => void loadMore()}
            disabled={loadingMore}
            className="h-9 rounded-lg border border-line px-4 text-[13px] text-muted transition hover:text-ink disabled:opacity-50"
          >
            {loadingMore ? "加载中…" : "加载更多"}
          </button>
        </div>
      ) : accounts.length ? (
        <p className="mt-6 text-center text-[11px] text-fade">名单到底了</p>
      ) : null}
    </div>
  );
}
