import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronRight,
  ExternalLink,
  Loader2,
  RefreshCw,
  UserRound,
} from "lucide-react";
import {
  getJSON,
  postJSON,
  prefetchDetail,
  prefetchItem,
  type AuthorFetchResult,
  type AuthorPageResponse,
  type FollowingItem,
} from "../api";
import { num, timeAgo } from "../format";
import { platform } from "../platform";

function when(item: FollowingItem): string {
  if (item.time_estimated || !item.published_at) return "时间未知";
  return timeAgo(item.published_at);
}

function AuthorItemRow({ item, from }: { item: FollowingItem; from: string }) {
  const p = platform(item.platform);
  return (
    <Link
      to={"/item/" + encodeURIComponent(item.id)}
      state={{ from, item }}
      onMouseEnter={() => prefetchItem(item.id)}
      onFocus={() => prefetchItem(item.id)}
      onClick={() => prefetchDetail(item.id)}
      className="group flex gap-3 px-3.5 py-3.5 transition hover:bg-wash/55"
    >
      <span
        className="relative h-[62px] w-[88px] shrink-0 overflow-hidden rounded-md bg-wash"
        style={{ background: p.tint + "14" }}
      >
        <span className="absolute inset-0 flex items-center justify-center text-[11px] text-fade">
          {item.kind === "video" ? "视频" : item.kind === "images" ? "图文" : "文章"}
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
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5 text-[11px] text-fade">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: p.tint }} />
          {p.label}
          <span>·</span>
          {when(item)}
        </span>
        <span className="mt-1 line-clamp-2 block text-[13.5px] font-medium leading-snug text-ink">
          {item.title}
        </span>
        {item.text ? (
          <span className="mt-1 line-clamp-2 block text-[12px] leading-relaxed text-muted">{item.text}</span>
        ) : null}
        <span className="mt-1 flex items-center gap-2.5 text-[11px] text-fade">
          {item.like_count ? <span>赞 {num(item.like_count)}</span> : null}
          {item.comment_count ? <span>评 {num(item.comment_count)}</span> : null}
        </span>
      </span>
      <ChevronRight size={14} className="mt-5 shrink-0 text-fade opacity-0 transition group-hover:opacity-100" />
    </Link>
  );
}

export default function AuthorPage() {
  const { platform: platformId = "", accountId = "" } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const [data, setData] = useState<AuthorPageResponse | null>(null);
  const [items, setItems] = useState<FollowingItem[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [note, setNote] = useState("");
  const autoTried = useRef(false);

  const base = "/api/authors/" + encodeURIComponent(platformId) + "/" + encodeURIComponent(accountId);
  const from = ((location.state as { from?: string } | null)?.from) || "/following";
  const current = "/author/" + encodeURIComponent(platformId) + "/" + encodeURIComponent(accountId);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const d = await getJSON<AuthorPageResponse>(base + "?limit=30");
      setData(d);
      setItems(d.items);
      setNext(d.next);
      setNote("");
      document.title = (d.profile.name || "作者") + " · OneFeed";
    } catch (err) {
      setNote((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [base]);

  useEffect(() => {
    void load();
  }, [load]);

  const fetchRemote = useCallback(async () => {
    setFetching(true);
    setNote("");
    try {
      const r = await postJSON<AuthorFetchResult>(base + "/fetch", { limit: 30 });
      if (!r.ok) setNote(r.error || "平台没有给这一页");
      await load();
    } catch (err) {
      setNote((err as Error).message);
    } finally {
      setFetching(false);
    }
  }, [base, load]);

  useEffect(() => {
    if (!data || autoTried.current) return;
    if (data.total > 0 || !data.remote_supported) return;
    autoTried.current = true;
    void fetchRemote();
  }, [data, fetchRemote]);

  const reloadProfile = async () => {
    try {
      const d = await getJSON<AuthorPageResponse>(base + "?limit=30&refresh=true");
      setData(d);
      setItems(d.items);
      setNext(d.next);
    } catch (err) {
      setNote((err as Error).message);
    }
  };

  const loadMore = async () => {
    if (!next) return;
    try {
      const d = await getJSON<{ items: FollowingItem[]; next: string | null; total: number }>(
        base + "/posts?limit=30&cursor=" + encodeURIComponent(next),
      );
      setItems((prev) => {
        const seen = new Set(prev.map((i) => i.id));
        return prev.concat(d.items.filter((i) => !seen.has(i.id)));
      });
      setNext(d.next);
    } catch (err) {
      setNote((err as Error).message);
    }
  };

  const profile = data?.profile;
  const p = platform(platformId);
  const counts = [
    ["关注", profile?.following_count],
    ["粉丝", profile?.follower],
    ["作品", profile?.posts],
  ].filter(([, v]) => typeof v === "number" && v > 0) as [string, number][];

  return (
    <div className="pb-28 pt-6">
      <div className="flex items-center gap-3">
        <button
          onClick={() => navigate(from)}
          className="inline-flex h-8 items-center gap-1.5 rounded-full border border-line px-3 text-[12px] text-muted transition hover:text-ink"
        >
          <ArrowLeft size={13} />
          返回
        </button>
        <span className="text-[11px] text-fade">作者主页</span>
      </div>

      {loading && !profile ? (
        <div className="mt-6 flex items-center gap-3 rounded-xl border border-line bg-paper p-4">
          <div className="h-14 w-14 animate-pulse rounded-full bg-wash" />
          <div className="flex-1 space-y-2">
            <div className="h-4 w-40 animate-pulse rounded bg-wash" />
            <div className="h-3 w-3/5 animate-pulse rounded bg-wash" />
          </div>
        </div>
      ) : profile ? (
        <header className="mt-5 flex flex-wrap items-start gap-4 rounded-xl border border-line bg-paper p-4">
          {profile.avatar ? (
            <img
              src={profile.avatar}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
              className="h-16 w-16 shrink-0 rounded-full object-cover"
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).style.display = "none";
              }}
            />
          ) : (
            <span
              className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full text-[20px] font-medium text-white"
              style={{ background: p.tint }}
            >
              {(profile.name || "?").slice(0, 1)}
            </span>
          )}
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="font-display text-[20px] font-semibold tracking-tight">
                {profile.name || "未命名作者"}
              </h1>
              <span className="inline-flex h-[18px] items-center rounded-full px-1.5 text-[11px] font-medium leading-none text-white" style={{ background: p.tint }}>
                {profile.label || p.label}
              </span>
              {profile.following ? <span className="text-[11px] text-accent">已关注</span> : null}
            </div>
            <p className="mt-1 line-clamp-2 text-[12px] leading-relaxed text-muted">
              {profile.bio || "这个作者没写简介。"}
            </p>
            {counts.length ? (
              <div className="mt-2 flex items-center gap-4 text-[11px] text-muted">
                {counts.map(([label, value]) => (
                  <span key={label}>
                    <span className="font-medium tabular-nums text-ink">{num(value)}</span> {label}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {profile.url ? (
              <a
                href={profile.url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex h-8 items-center gap-1.5 rounded-full border border-line px-3 text-[12px] text-muted transition hover:text-ink"
              >
                去平台主页
                <ExternalLink size={12} />
              </a>
            ) : null}
            <button
              onClick={() => void reloadProfile()}
              title="重新读作者名片"
              aria-label="重新读作者名片"
              className="flex h-8 w-8 items-center justify-center rounded-full border border-line text-muted transition hover:text-ink"
            >
              <RefreshCw size={13} />
            </button>
          </div>
        </header>
      ) : (
        <div className="mt-6 rounded-xl border border-line bg-paper px-5 py-10 text-center">
          <UserRound size={22} className="mx-auto text-fade" />
          <p className="mt-2 text-[14px] font-medium text-ink">找不到这个作者</p>
          <p className="mt-1.5 text-[12px] text-muted">{note || "平台没给资料，也可能是链接不完整。"}</p>
        </div>
      )}

      {note ? <p className="mt-3 text-[12px] text-danger">{note}</p> : null}
      {data?.profile_error ? <p className="mt-2 text-[11px] text-danger">{data.profile_error}</p> : null}
      {data?.plugin_errors?.length ? (
        <p className="mt-2 text-[11px] text-danger">{data.plugin_errors.join("；")}</p>
      ) : null}

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <h2 className="text-[13px] font-medium text-ink">最近发布</h2>
        <span className="text-[11px] text-fade">{data?.total ?? 0} 条</span>
        <div className="ml-auto flex items-center gap-2">
          {data?.remote_supported ? (
            <button
              onClick={() => void fetchRemote()}
              disabled={fetching}
              className="inline-flex h-8 items-center gap-1.5 rounded-full border border-line px-3 text-[12px] text-ink transition hover:bg-wash disabled:opacity-50"
            >
              {fetching ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
              {fetching ? "正在补一页…" : "从平台补一页"}
            </button>
          ) : (
            <span className="text-[11px] text-fade">这个平台暂时不能补历史作品</span>
          )}
        </div>
      </div>

      {items.length ? (
        <div className="mt-2 divide-y divide-line/60 overflow-hidden rounded-xl border border-line bg-paper">
          {items.map((item) => (
            <AuthorItemRow key={item.id} item={item} from={current} />
          ))}
        </div>
      ) : !loading ? (
        <div className="mt-2 rounded-xl border border-line bg-paper px-5 py-9 text-center">
          <p className="text-[13px] text-ink">这个作者还没有入库的内容</p>
          <p className="mt-1.5 text-[12px] text-muted">
            {data?.remote_supported ? "点「从平台补一页」抓第一页回来。" : "等关注流同步到他的内容，或者去平台看。"}
          </p>
        </div>
      ) : null}

      {next ? (
        <div className="mt-5 flex justify-center">
          <button
            onClick={() => void loadMore()}
            className="h-9 rounded-lg border border-line px-4 text-[13px] text-muted transition hover:text-ink"
          >
            加载更多
          </button>
        </div>
      ) : null}

      {!data?.remote_supported && platformId !== "bilibili" ? (
        <p className="mt-4 flex items-center gap-1.5 text-[11px] text-fade">
          <AlertTriangle size={12} />
          目前只有 B 站插件能按作者补历史作品，其他平台先看本地已同步的内容。
        </p>
      ) : null}
    </div>
  );
}
