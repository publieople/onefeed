import { useCallback, useEffect, useRef, useState } from "react";

export interface FeedItem {
  id: string;
  platform: string;
  kind: string;
  title: string;
  text: string;
  author: string;
  author_id: string;
  author_avatar: string;
  cover: string;
  images: string[];
  tags: string[];
  extra: Record<string, unknown>;
  url: string;
  published_at: number;
  duration: number;
  like_count: number;
  comment_count: number;
  share_count: number;
  view_count: number;
  cluster_id: string;
  cluster_size: number;
  cluster_platforms: string[];
  reasons: string[];
  fetched_at: number;
}

export interface ParsedQuery {
  raw: string;
  platforms: string[];
  kinds: string[];
  since: number | null;
  keyword: string;
  understood: boolean;
}

export interface FeedResponse {
  items: FeedItem[];
  next: string | null;
  count: number;
  parsed: ParsedQuery | null;
}

export interface Summary {
  text: string;
  total: number;
  platforms: { platform: string; count: number; last_fetched_at: number }[];
  updated_at: number;
  offline: boolean;
}

export interface RunState {
  running: boolean;
  started_at: number;
  finished_at: number;
  done: number;
  total: number;
  error: string;
  plugins: Record<string, { status: string; count: number; error: string; ms: number }>;
}

export interface MarketEntry {
  id: string;
  name: string;
  version: string;
  description: string;
  author: string;
  kinds: string[];
  capabilities: string[];
  installed: boolean;
  installed_version: string;
  latest_version?: string;
  enabled: boolean;
  update_available: boolean;
  features?: string[];
}

export interface InstalledPlugin {
  id: string;
  version: string;
  enabled: number;
  source: string;
  name?: string;
  description?: string;
  capabilities?: string[];
  features?: string[];
}

export interface PluginsResponse {
  installed: InstalledPlugin[];
  market: { entries: MarketEntry[]; degraded: string; from_cache: boolean; url: string };
  plugins_dir?: string;
  errors?: string[];
}

export interface AuthState {
  plugin: string;
  state: "not_required" | "available" | "need_login" | "error";
  message?: string;
  hint?: string;
  can_login?: boolean;
  cli?: boolean;
  label?: string;
  login_url?: string;
  impact?: string;
  command?: string;
  cookies?: number;
}

export interface LoginStatus {
  plugin: string;
  state: "idle" | "opened" | "waiting" | "ok" | "closed" | "error";
  message?: string;
  cookies?: number;
  url?: string;
  port?: number;
  cookie?: string;
}

export interface AiProvider {
  id: string;
  name: string;
  base_url: string;
  model: string;
  enabled: boolean;
  /** 只写不读：已保存的 key 返回空串 */
  key?: string;
  key_set?: boolean;
  key_hint?: string;
}

export interface SettingsValues {
  plugins_dir: string;
  registry_url: string;
  per_plugin_limit: number;
  comments_limit: number;
  default_sort: string;
  prune_days: number;
  auto_update: boolean;
  ai_base_url: string;
  ai_model: string;
  /** 只写不读：后端返回时永远为空串 */
  ai_api_key: string;
  /** 按顺序试的模型表；空数组时退回上面那组单模型字段 */
  ai_providers: AiProvider[];
}

export interface SettingsResponse {
  settings: SettingsValues;
  ai: AiStatus;
  resolved: { plugins_dir: string; registry_url: string; state_dir?: string };
  defaults: SettingsValues;
  sorts: string[];
}

export interface CommentItem {
  id: string;
  author: string;
  author_id?: string;
  text: string;
  like_count?: number;
  reply_count?: number;
  created_at?: number;
  replies?: CommentItem[];
}

export interface CommentsResponse {
  supported: boolean;
  items: CommentItem[];
  count: number;
  limit?: number;
  /** 下一页游标；null/缺省表示插件取不到更多了 */
  next?: string | null;
  reason?: string;
  hint?: string;
  error?: string;
  from_cache?: boolean;
}

export interface DetailBody {
  kind: "html" | "markdown" | "text";
  value: string;
}

export interface DetailMedia {
  type: "embed" | "file";
  embedUrl?: string;
  /** 官方播放器失败时的兜底直链，走 /api/media/<id>/video 边车 */
  fallbackUrl?: string;
  fallbackReferer?: string;
  url?: string;
  poster?: string;
  referer?: string;
  duration?: number;
  expiresAt?: number;
}

export interface DetailPayload {
  body?: DetailBody;
  media?: DetailMedia;
  images?: string[];
  stats?: Record<string, number>;
  note?: string;
}

export interface DetailResponse {
  supported: boolean;
  detail: DetailPayload | null;
  from_cache?: boolean;
  fetched_at?: number;
  reason?: string;
  error?: string;
}

export interface AiPlan {
  mode: "find" | "browse";
  platforms: string[];
  kinds: string[];
  since: number | null;
  keyword: string;
  sort: string;
}

export interface AiResponse {
  engine: "llm" | "rules";
  /** 这一轮实际回答的是哪个模型（规则解析时为空） */
  provider?: string;
  plan: AiPlan;
  reply: string;
  items: FeedItem[];
  count: number;
  suggestions: string[];
  understood: string;
}

export interface AiProviderStatus {
  id: string;
  name: string;
  base_url: string;
  model: string;
  key_set: boolean;
  key_hint: string;
}

export interface AiAttempt {
  at: number;
  provider: string;
  ok: boolean;
  error: string;
  tried: string[];
}

export interface AiStatus {
  engine: "llm" | "rules";
  model: string;
  base_url: string;
  configured: boolean;
  active?: string;
  providers?: AiProviderStatus[];
  last?: AiAttempt;
  platforms: string[];
  kinds: string[];
}

export interface AiTestResult {
  ok: boolean;
  ms?: number;
  provider?: string;
  model?: string;
  reply?: string;
  error?: string;
}

/** 测一个模型通不通：传已保存的 id，或传还没保存的 base_url + model + key */
export function aiTest(body: Record<string, unknown>): Promise<AiTestResult> {
  return postJSON<AiTestResult>("/api/ai/test", body);
}

export function aiChat(message: string, extra: Record<string, unknown> = {}): Promise<AiResponse> {
  return postJSON<AiResponse>("/api/ai/chat", { message, ...extra });
}

export function aiStatus(signal?: AbortSignal): Promise<AiStatus> {
  return getJSON<AiStatus>("/api/ai/status", signal);
}

export function getDetail(id: string, refresh = false, signal?: AbortSignal): Promise<DetailResponse> {
  const qs = refresh ? "?refresh=1" : "";
  return getJSON<DetailResponse>("/api/item/" + encodeURIComponent(id) + "/detail" + qs, signal);
}

export interface Health {
  ok: boolean;
  version: string;
  items: number;
  db: string;
  plugins: number;
  platforms: { platform: string; count: number; last_fetched_at: number }[];
  demo: boolean;
  refreshing: boolean;
}

export class ApiError extends Error {
  code: string;
  constructor(message: string, code = "http_error") {
    super(message);
    this.code = code;
  }
}

export async function getJSON<T>(path: string, signal?: AbortSignal): Promise<T> {
  const resp = await fetch(path, { signal, headers: { Accept: "application/json" } });
  if (!resp.ok) {
    let message = `请求失败（${resp.status}）`;
    try {
      const body = await resp.json();
      message = body?.detail?.message ?? body?.error?.message ?? message;
    } catch {
      /* 保持默认文案 */
    }
    throw new ApiError(message);
  }
  return (await resp.json()) as T;
}

export async function postJSON<T>(path: string, body: unknown = {}): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new ApiError(data?.detail?.message ?? `请求失败（${resp.status}）`);
  }
  return data as T;
}

export async function putJSON<T>(path: string, body: unknown = {}): Promise<T> {
  const resp = await fetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    throw new ApiError(data?.detail?.message ?? body2message(data) ?? `请求失败（${resp.status}）`);
  }
  return data as T;
}

function body2message(data: unknown): string | undefined {
  const d = data as { error?: { message?: string } } | undefined;
  return d?.error?.message;
}

export async function deleteJSON<T>(path: string): Promise<T> {
  const resp = await fetch(path, { method: "DELETE" });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new ApiError(data?.detail?.message ?? "删除失败");
  return data as T;
}

export interface FeedQuery {
  platforms: string[];
  kind: string;
  sort: string;
  q: string;
  since?: number | null;
}

export function useFeed(query: FeedQuery, reloadKey: number) {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [count, setCount] = useState(0);
  const [parsed, setParsed] = useState<ParsedQuery | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  const build = useCallback(
    (cursor: string | null) => {
      const params = new URLSearchParams();
      if (query.platforms.length) params.set("platform", query.platforms.join(","));
      if (query.kind) params.set("kind", query.kind);
      if (query.sort) params.set("sort", query.sort);
      if (query.q.trim()) params.set("q", query.q.trim());
      if (query.since) params.set("since", String(query.since));
      if (cursor) params.set("cursor", cursor);
      params.set("limit", "30");
      return "/api/feed?" + params.toString();
    },
    [query.platforms.join(","), query.kind, query.sort, query.q, query.since ?? 0],
  );

  const load = useCallback(
    async (cursor: string | null, append: boolean) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setLoading(true);
      setError("");
      try {
        const data = await getJSON<FeedResponse>(build(cursor), controller.signal);
        setItems((prev) => (append ? [...prev, ...data.items] : data.items));
        setNext(data.next);
        setCount(data.count);
        setParsed(data.parsed);
      } catch (err) {
        if ((err as Error).name !== "AbortError") setError((err as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [build],
  );

  useEffect(() => {
    void load(null, false);
  }, [load, reloadKey]);

  return {
    items,
    next,
    count,
    parsed,
    loading,
    error,
    more: () => (next ? load(next, true) : Promise.resolve()),
  };
}