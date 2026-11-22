/**
 * 静态演示站（specs/012-demo-site）。
 *
 * VITE_DEMO=1 时这里接管所有 /api 请求：数据来自构建期导出的 demo/api.json，
 * 写操作一律拒绝并说明去哪真用。拦截放在 fetch 这一层，页面里直接 fetch 的地方
 * （设置页的插件开关、裸 SSE）也一起覆盖，不用逐页改。
 *
 * 刻意不做的两件事：把平台登录态塞进 localStorage、在浏览器里打包平台插件。
 * 前者取不到也存不住（cookie 是 HttpOnly + 跨域），后者根本没有运行时。
 */
import type {
  AuthRow,
  AuthState,
  CommentsResponse,
  DetailResponse,
  FeedItem,
  FeedResponse,
  Health,
  ItemResponse,
  LoginStatus,
  PluginsResponse,
  RunState,
  SettingsResponse,
  Summary,
} from "./api";
import { PLATFORMS } from "./platform";

export const DEMO = import.meta.env.VITE_DEMO === "1";
const BASE = import.meta.env.BASE_URL;

interface SnapshotMeta {
  generated_at: number;
  version: string;
  items: number;
  newest_published_at: number;
  fixtures_saved_at: Record<string, number>;
  platforms: string[];
}

interface Snapshot {
  meta: SnapshotMeta;
  health: Health;
  summary: Summary;
  settings: SettingsResponse;
  feed: FeedResponse;
}

let cached: Promise<Snapshot> | null = null;

export function snapshot(): Promise<Snapshot> {
  if (!cached) {
    cached = fetch(BASE + "demo/api.json", { headers: { Accept: "application/json" } })
      .then(async (resp) => {
        if (!resp.ok) throw new Error(`演示数据没找到（HTTP ${resp.status}）：${BASE}demo/api.json`);
        return (await resp.json()) as Snapshot;
      })
      .catch((err: unknown) => {
        cached = null;
        throw err;
      });
  }
  return cached;
}

// 静态站没有采集循环：前端只关心 running / plugins，其余字段按后端 RunState 走。
// 用断言而不是精确字面量，后端给 RunState 加字段时这里不用跟着改（phase / new_total 就是这么来的）。
const IDLE = {
  running: false,
  started_at: 0,
  finished_at: 0,
  done: 0,
  total: 0,
  error: "",
  plugins: {},
} as unknown as RunState;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

/** 只读操作被拦时的统一说法：告诉用户去哪能真做这件事 */
function readonlyResponse(what: string): Response {
  return json(
    {
      detail: {
        code: "demo_readonly",
        message: `静态演示站不能${what}：要真用得在本机跑 uv run python -m onefeed。`,
      },
    },
    503,
  );
}

function stripBase(pathname: string): string {
  let path = pathname;
  if (BASE !== "/" && path.startsWith(BASE)) path = "/" + path.slice(BASE.length);
  return path.length > 1 ? path.replace(/\/+$/, "") : path;
}

function sameCluster(snap: Snapshot, item: FeedItem): ItemResponse["siblings"] {
  if (!item.cluster_id) return [];
  return snap.feed.items
    .filter((other) => other.id !== item.id && other.cluster_id === item.cluster_id)
    .map((other) => ({
      id: other.id,
      platform: other.platform,
      title: other.title,
      author: other.author,
      url: other.url,
      published_at: other.published_at,
    }));
}

/** 平台轮转交错是后端做的；静态站按单一时间序排，翻页也就不需要游标了 */
/** 与 store.FRESH_KEY 同口径：没有发布时间就退回抓取时刻。 */
function freshKey(item: FeedItem): number {
  return item.published_at || item.fetched_at || 0;
}

function feedFrom(snap: Snapshot, params: URLSearchParams): FeedResponse {
  const platforms = (params.get("platform") || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const kind = (params.get("kind") || "").trim();
  const q = (params.get("q") || params.get("keyword") || "").trim().toLowerCase();
  const saved = params.get("saved") === "1";
  const since = Number(params.get("since") || 0) || 0;
  const sort = (params.get("sort") || "freshness").trim();
  const limit = Math.max(1, Math.min(100, Number(params.get("limit") || 18) || 18));

  // 快照是历史数据，前端传的 since 是「真实世界的绝对时刻」（今天零点）。
  // 把整条时间轴平移到快照最新一条上，否则「今天」永远是空的、或者全量都过。
  const anchor = snap.meta.newest_published_at || snap.feed.items.reduce((m, i) => Math.max(m, freshKey(i)), 0);
  const shift = anchor - Date.now() / 1000;
  const cutoff = since > 0 ? since + shift : 0;

  let items = snap.feed.items.filter((item) => {
    if (platforms.length && !platforms.includes(item.platform)) return false;
    if (kind && item.kind !== kind) return false;
    if (saved && !(item.saved || item.favorited)) return false;
    if (cutoff > 0 && freshKey(item) < cutoff) return false;
    if (q) {
      const hay = [item.title, item.text, item.author, (item.tags || []).join(" ")].join("\n").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });

  // 快照已经是宿主那套「各平台各排各队、再轮流拼」的顺序，筛选后保序即可；
  // 重新按时间全局排序会退化成整屏同一个平台，跟本地实例不是一回事。
  if (sort === "engage") {
    const score = (item: FeedItem) =>
      (item as FeedItem & { engage_score?: number }).engage_score ?? item.like_count ?? 0;
    items = [...items].sort((a, b) => score(b) - score(a));
  }

  return { items: items.slice(0, limit), count: items.length, next: null, parsed: null };
}

function pluginsFrom(snap: Snapshot): PluginsResponse {
  const counts = new Map<string, number>();
  for (const item of snap.feed.items) counts.set(item.platform, (counts.get(item.platform) ?? 0) + 1);
  const installed = PLATFORMS.filter((p) => counts.has(p.id)).map((p) => ({
    id: p.id,
    version: "snapshot",
    enabled: 1,
    source: "fixture",
    name: p.label,
    description: `快照里有 ${counts.get(p.id)} 条`,
    capabilities: ["read"],
  }));
  return {
    installed,
    market: {
      entries: [],
      degraded: "静态演示不连插件市场：装插件、更新版本都要在本机运行。",
      from_cache: false,
      url: "",
    },
    plugins_dir: "",
    errors: [],
  };
}

function authRows(): { rows: AuthRow[] } {
  return {
    rows: PLATFORMS.map((p) => ({
      plugin: p.id,
      can_login: false,
      cli: false,
      label: p.label,
      impact: "静态站没有本机浏览器档案，登录态无处可存。",
      hint: "本机运行后设置页会打开平台窗口，扫码即用。",
    })),
  };
}

function routeGet(snap: Snapshot, path: string, params: URLSearchParams): Response {
  if (path === "/api/health") return json(snap.health);
  if (path === "/api/summary") return json(snap.summary);
  if (path === "/api/settings") return json(snap.settings);
  if (path === "/api/progress") return json({ state: IDLE });
  if (path === "/api/feed") return json(feedFrom(snap, params));
  if (path === "/api/plugins") return json(pluginsFrom(snap));
  if (path === "/api/auth") return json(authRows());
  if (path === "/api/favorites") return json({ items: [], count: 0 });
  if (path === "/api/ai/status")
    return json({
      engine: "rules",
      agent: false,
      model: "",
      base_url: "",
      configured: false,
      providers: [],
      platforms: PLATFORMS.map((p) => p.id),
      kinds: ["video", "images", "article", "short", "list"],
    });
  if (path === "/api/agent/threads") return json({ threads: [] });
  if (path === "/api/agent/saved") return json({ items: [], count: 0 });
  if (path === "/api/agent/summaries") return json({ items: [], count: 0 });
  if (path === "/api/agent/runs") return json({ runs: [], count: 0 });
  if (path.startsWith("/api/agent/threads/")) return json({ thread_id: path.split("/").pop(), runs: [] });
  if (path.startsWith("/api/agent/runs/"))
    return json({ detail: { message: "演示站没有 Agent 运行记录：Agent 需要在本机连模型。" } }, 404);

  const authMatch = path.match(/^\/api\/auth\/([^/]+)(\/login\/status)?$/);
  if (authMatch) {
    const plugin = decodeURIComponent(authMatch[1]);
    if (authMatch[2]) {
      const status: LoginStatus = { plugin, state: "error", message: "静态站不能登录。" };
      return json(status);
    }
    const state: AuthState = {
      plugin,
      state: "not_required",
      can_login: false,
      message: "静态演示不使用任何账号。",
      hint: "在本机运行后，设置页会给出扫码入口。",
    };
    return json(state);
  }

  const favMatch = path.match(/^\/api\/favorites\/(.+)$/);
  if (favMatch) return json({ item_id: decodeURIComponent(favMatch[1]), favorited: false, note: "", created_at: 0, updated_at: 0 });

  const itemMatch = path.match(/^\/api\/item\/([^/]+)(\/[a-z]+)?$/);
  if (itemMatch) {
    const id = decodeURIComponent(itemMatch[1]);
    const item = snap.feed.items.find((row) => row.id === id);
    if (!item) return json({ detail: { message: "演示快照里没有这条内容（可能不在这次导出的样本里）。" } }, 404);
    const tail = itemMatch[2];
    if (tail === "/detail") {
      const body: DetailResponse = {
        supported: false,
        detail: null,
        reason: "静态演示不带正文与评论：详情要现抓，只有本机运行时才有。",
      };
      return json(body);
    }
    if (tail === "/comments") {
      const body: CommentsResponse = {
        supported: false,
        items: [],
        count: 0,
        reason: "静态演示不带评论：评论要现抓，只有本机运行时才有。",
      };
      return json(body);
    }
    if (tail === "/summary") return json({ ok: false, error: "静态演示站没有模型，生成不了总结。" });
    return json({ item, siblings: sameCluster(snap, item) });
  }

  return json({ detail: { message: `静态演示没有这个接口：${path}` } }, 404);
}

async function handle(input: string, init?: RequestInit): Promise<Response> {
  const snap = await snapshot();
  const url = new URL(input, window.location.origin);
  const path = stripBase(url.pathname);
  const method = (init?.method || "GET").toUpperCase();

  if (method === "GET") return routeGet(snap, path, url.searchParams);
  if (method === "POST" && path === "/api/refresh") return json({ ok: true, state: IDLE });
  if (method === "POST" && path === "/api/agent/undo") return json({ ok: false, message: "演示站没有可撤销的动作。" });
  if (method === "POST" && path === "/api/agent/save") return json({ ok: true, saved: true });
  if (method === "POST" && path === "/api/agent/mark") return json({ ok: true, mark: { saved: false, read: false, hidden: false } });

  if (method === "POST" || method === "PUT" || method === "PATCH" || method === "DELETE") {
    return readonlyResponse(path === "/api/settings" ? "保存设置" : "执行这个操作");
  }
  return readonlyResponse("执行请求");
}

let installed = false;

function install(): void {
  if (installed) return;
  installed = true;
  const original = window.fetch.bind(window);
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const raw =
      typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    const url = new URL(raw, window.location.origin);
    const path = stripBase(url.pathname);
    // 快照文件自己不是 API；流式接口由 api.ts 直接给降级文案，这里放过去只会变成 404
    if (path.startsWith("/api/") && !path.endsWith("/stream")) {
      return handle(url.pathname + url.search, init);
    }
    return original(input, init);
  };
}

if (DEMO) install();
