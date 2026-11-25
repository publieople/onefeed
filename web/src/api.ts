import { useCallback, useEffect, useRef, useState } from "react";
import { seedSaved } from "./agent/savedStore";
import { DEMO } from "./demo";

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
  /** 直播动态不进信息流：存量条目仍能直接打开，页面上要说明清楚 */
  is_live?: boolean;
  /** 作者页补回来的历史作品：只属于作者页，不进主信息流/关注流 */
  author_only?: boolean;
  /** item_marks 拍平：收藏 / 已读（后端 page() 会带） */
  saved?: boolean;
  read?: boolean;
  /** 收藏时间（秒）：稍后再看按它倒序，没有就是没收藏过 */
  saved_at?: number;
  note?: string;
  /** 收藏夹是另一张表：与稍后再看互不影响 */
  favorited?: boolean;
  favorite_note?: string;
}

export type FollowingLayout = "list" | "timeline" | "compact";

/** 关注流条目：比信息流多三项，时间未知时按首次看到时间排 */
export interface FollowingItem extends FeedItem {
  following?: boolean;
  time_estimated?: boolean;
  feed_first_seen_at?: number;
  feed_last_seen_at?: number;
}

export interface FollowingPlatform {
  platform: string;
  label: string;
  installed: boolean;
  supported: boolean;
  logged_in: boolean | null;
  /** not_installed / unsupported / need_login / ready */
  state: string;
  note: string;
  count: number;
  last_seen_at: number;
  last_sync_at: number;
  last_ok_at: number;
  last_ok: boolean | null;
  saved_count?: number;
  new_count?: number;
  total?: number;
  error: string;
}

export interface FollowingCount {
  platform: string;
  count: number;
  last_seen_at: number;
}

export interface FollowingResponse {
  items: FollowingItem[];
  next: string | null;
  count: number;
  platforms: FollowingPlatform[];
  plugin_errors?: string[];
  counts: FollowingCount[];
  total: number;
  syncing: boolean;
  progress: RunState;
}

/** 关注名单里的一个人（不是他发的某条内容） */
export interface FollowingAccount {
  account_id: string;
  platform: string;
  name: string;
  avatar: string;
  url: string;
  bio: string;
  relation: string;
  active?: number | boolean;
  followed_at?: number;
  first_seen_at?: number;
  last_seen_at?: number;
  extra?: Record<string, unknown>;
}

export interface FollowingAccountsResponse {
  accounts: FollowingAccount[];
  next: number | null;
  count: number;
  total: number;
  platforms: FollowingPlatform[];
  plugin_errors?: string[];
  counts: FollowingCount[];
  syncing: boolean;
  progress: RunState;
}

export interface AuthorProfile {
  platform: string;
  account_id: string;
  name: string;
  avatar: string;
  url: string;
  bio: string;
  label: string;
  following: boolean;
  relation?: string;
  following_count?: number;
  follower?: number;
  posts?: number;
}

export interface AuthorPageResponse {
  profile: AuthorProfile;
  profile_error: string;
  items: FollowingItem[];
  next: string | null;
  count: number;
  total: number;
  remote_supported: boolean;
  platforms: FollowingPlatform[];
  plugin_errors?: string[];
}

export interface AuthorFetchResult {
  ok: boolean;
  error: string;
  fetched: number;
  added: number;
  next: string | null;
  total: number;
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
  /** idle / fetching / settling / done / partial / empty / cancelled —— 整理中、全冷却、被叫停要分开说 */
  phase?: "idle" | "fetching" | "settling" | "done" | "partial" | "empty" | "cancelled" | string;
  /** 这一轮真正新入库的条数（不是「抓到了几条」） */
  new_total?: number;
  /** user = 顶栏按钮；agent = Agent 自己判断要抓。主信息流只认 user */
  source?: "user" | "agent" | string;
  owner?: string;
  cancel_requested?: boolean;
  cancelled?: number;
  market?: { checked: number; updated: string[]; failed: { id: string; error: string }[] };
  plugins: Record<
    string,
    {
      status: string;
      count: number;
      new_count?: number;
      label?: string;
      error: string;
      ms: number;
      note?: string;
      next_at?: number;
    }
  >;
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

/** /api/auth 返回的登录行：哪些平台有登录流程以后端为准，前端不再抄名单 */
export interface AuthRow {
  plugin: string;
  can_login?: boolean;
  cli?: boolean;
  label?: string;
  login_url?: string;
  impact?: string;
  cookie_names?: string[];
  hint?: string;
  command?: string;
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
  /** {平台: 秒}，0 = 该平台不限制；空表表示全用内置默认 */
  platform_intervals: Record<string, number>;
  auto_update: boolean;
  /** 库里 0 条时让 Agent 自动去平台抓一轮再查（每轮一次，仍受平台间隔限制） */
  agent_auto_pull: boolean;
  /** 总结时是否把图片交给多模态模型（关掉只读文字，省钱） */
  vision_summary: boolean;
  /** 新打开一条时用哪档总结粒度：brief / balanced / detailed */
  summary_depth?: SummaryDepth | string;
  /** 关注页默认布局：list / timeline / compact */
  following_layout?: FollowingLayout | string;
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
  /** 生效中的平台冷却（内置默认 + 覆盖），设置页用它填初始值 */
  intervals?: Record<string, number>;
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
  mode: "find" | "browse" | "agent";
  platforms: string[];
  kinds: string[];
  since: number | null;
  keyword: string;
  sort: string;
}

export interface AiResponse {
  engine: "llm" | "rules" | "agent";
  /** 这一轮实际回答的是哪个模型（规则解析时为空） */
  provider?: string;
  plan: AiPlan;
  reply: string;
  items: FeedItem[];
  count: number;
  suggestions: string[];
  understood: string;
  /** Agent 路径：这次实际查了几次、花了多久 */
  steps?: number;
  ms?: number;
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
  /** 模型能自己调工具检索（走 Agent 路径）；关掉后回到「一次出计划」 */
  agent?: boolean;
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

/** 设置页「登录态」的行清单（含 can_login / cli 标记） */
export function authRows(): Promise<{ rows: AuthRow[] }> {
  return getJSON("/api/auth");
}

export function aiChat(message: string, extra: Record<string, unknown> = {}): Promise<AiResponse> {
  return postJSON<AiResponse>("/api/ai/chat", { message, ...extra });
}

/* ---------------------------------------------------------------- Agent 运行 */

/** 运行事件：SSE 的每一帧，和回放读的是同一份 */
export interface AgentEvent {
  seq: number;
  kind:
    | "run_start"
    | "plan"
    | "step"
    | "tool"
    | "action"
    | "need_confirm"
    | "need_answer"
    | "delta"
    | "done"
    | "cancelled"
    | "error"
    | string;
  name: string;
  data: Record<string, any>;
  undo_token?: string;
  at: number;
}

export interface AgentStart {
  run_id: string;
  thread_id: string;
  status: string;
}

/** 起一轮 Agent。后端关掉 Agent 时抛 code=agent_unavailable，调用方回落 aiChat。 */
export async function agentStart(
  message: string,
  extra: Record<string, unknown> = {},
): Promise<AgentStart> {
  if (DEMO) {
    throw new ApiError("静态演示站没有 Agent：它需要模型和本机检索。", "agent_unavailable");
  }
  const resp = await fetch("/api/agent/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, ...extra }),
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    const err = (data?.error ?? data?.detail ?? {}) as { code?: string; message?: string };
    throw new ApiError(err.message ?? `请求失败（${resp.status}）`, err.code ?? "http_error");
  }
  return data as AgentStart;
}

/** 订阅一次运行的事件流；返回关闭函数。done 之后由调用方主动关，别等自动重连。 */
export function agentStream(
  runId: string,
  onEvent: (event: AgentEvent) => void,
  onFail: (message: string) => void,
): () => void {
  const es = new EventSource("/api/agent/runs/" + encodeURIComponent(runId) + "/events");
  es.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as AgentEvent);
    } catch {
      /* 坏帧忽略，别让整条流断掉 */
    }
  };
  es.onerror = () => {
    es.close();
    onFail("事件流断了");
  };
  return () => es.close();
}

export function agentConfirm(runId: string, confirmId: string, allow: boolean): Promise<{ ok: boolean }> {
  return postJSON("/api/agent/runs/" + encodeURIComponent(runId) + "/confirm", { confirm_id: confirmId, allow });
}

export function agentCancel(runId: string): Promise<{ ok: boolean }> {
  return postJSON("/api/agent/runs/" + encodeURIComponent(runId) + "/cancel", {});
}

/** 回答 Agent 的提问：选中的选项 + 可选自由文本，一起塞回等待中的那一轮 */
export function agentAnswer(
  runId: string,
  askId: string,
  selected: string[],
  text = "",
): Promise<{ ok: boolean }> {
  return postJSON("/api/agent/runs/" + encodeURIComponent(runId) + "/answer", {
    ask_id: askId,
    selected,
    text,
  });
}

export interface AgentThread {
  id: string;
  title: string;
  runs: number;
  updated_at: number;
}

export interface AgentThreadRun {
  id: string;
  input: string;
  reply: string;
  status: string;
  created_at: number;
  steps?: number;
  ms?: number;
  /** 这一轮的完整事件流：回放时从 done 事件的 payload 里复原结果卡片与轨迹 */
  events?: AgentEvent[];
}

/** 会话列表：面板里「最近」用，接着上一段聊不必重说条件 */
export function listThreads(limit = 8): Promise<{ threads: AgentThread[] }> {
  return getJSON("/api/agent/threads?limit=" + limit);
}

export function getThread(threadId: string): Promise<{ thread_id: string; runs: AgentThreadRun[] }> {
  return getJSON("/api/agent/threads/" + encodeURIComponent(threadId));
}

/** 结果卡片上的收藏，不经过模型 */
export function agentSave(id: string, on: boolean): Promise<{ ok: boolean; saved: boolean }> {
  return postJSON("/api/agent/save", { id, on });
}

export interface AgentMark {
  saved: boolean;
  read: boolean;
  hidden: boolean;
}

export function agentMark(id: string, patch: { saved?: boolean; read?: boolean; hidden?: boolean }): Promise<{ ok: boolean; mark: AgentMark }> {
  return postJSON("/api/agent/mark", { id, ...patch });
}

export function agentSaved(): Promise<{ items: FeedItem[]; count: number }> {
  return getJSON("/api/agent/saved");
}

/** 收藏夹：与稍后再看分开的两套接口 */
export interface FavoriteState {
  item_id: string;
  favorited: boolean;
  note: string;
  created_at: number;
  updated_at: number;
}

export function listFavorites(limit = 50): Promise<{ items: FeedItem[]; count: number }> {
  return getJSON("/api/favorites?limit=" + limit);
}

export function favoriteStatus(id: string): Promise<FavoriteState> {
  return getJSON("/api/favorites/" + encodeURIComponent(id));
}

/** 收藏必须带备注：那是它和「稍后再看」的区别 */
export function addFavorite(id: string, note: string): Promise<{ ok: boolean; favorite: FavoriteState }> {
  return putJSON("/api/favorites/" + encodeURIComponent(id), { note });
}

export function removeFavorite(id: string): Promise<{ ok: boolean; removed: boolean }> {
  return deleteJSON("/api/favorites/" + encodeURIComponent(id));
}

/** 最近总结过的条目：条目本体 + 那次的 tldr / 要点数 / 生成时间 */
export interface SummarizedItem extends FeedItem {
  summary_tldr?: string;
  summary_at?: number;
  summary_points?: number;
}

export function agentSummaries(limit = 30): Promise<{ items: SummarizedItem[]; count: number }> {
  return getJSON("/api/agent/summaries?limit=" + limit);
}

export function agentUndo(token: string): Promise<Record<string, unknown>> {
  return postJSON("/api/agent/undo", { token });
}

export interface AgentReplay {
  run: {
    id: string;
    thread_id: string;
    status: string;
    input: string;
    model: string;
    reply: string;
    steps: number;
    ms: number;
    tokens: number;
    error: string;
    created_at: number;
    finished_at: number;
    events: AgentEvent[];
  };
  events: AgentEvent[];
}

export function agentReplay(runId: string): Promise<AgentReplay> {
  return getJSON("/api/agent/runs/" + encodeURIComponent(runId));
}

/** 设置页「Agent 活动」用的一行：跑过什么、结果如何、哪些动作还能撤销 */
export interface AgentRunRow {
  id: string;
  thread_id: string;
  status: string;
  input: string;
  model: string;
  reply: string;
  error: string;
  steps: number;
  ms: number;
  tokens: number;
  created_at: number;
  finished_at: number;
  events?: AgentEvent[];
}

/** 最近几轮；events=1 才会带回事件（撤销按钮要拿 undo_token）。 */
export function agentRuns(limit = 8): Promise<{ runs: AgentRunRow[]; count: number }> {
  return getJSON("/api/agent/runs?limit=" + limit + "&events=1");
}


export function aiStatus(signal?: AbortSignal): Promise<AiStatus> {
  return getJSON<AiStatus>("/api/ai/status", signal);
}

/** 单条详情的外壳：主记录 + 同一件事在其他平台的那几条 */
export interface ItemResponse {
  item: FeedItem;
  siblings: { id: string; platform: string; title: string; author: string; url: string; published_at: number }[];
}

/**
 * 悬停预取。
 *
 * 沉浸式转场最怕「飞进去之后是骨架屏」：动画把一张卡片放大成页面，页面里却什么都没有。
 * 指针在卡片上停 260ms 就把首屏要的三份数据拉下来，点开时基本都是即时命中。
 * 缓存只活 60 秒——聚合器里的内容本来就变得快，预取过期了就当没有。
 */
const PREFETCH_TTL = 60_000;
const prefetched = new Map<string, { item?: ItemResponse; detail?: DetailResponse; at: number }>();

/** 预取表不能只进不出：一屏扫过去就是二三十条，滚一路会攒下整天的数据 */
const PREFETCH_MAX = 24;
function prunePrefetch(): void {
  const now = Date.now();
  for (const [key, slot] of prefetched) {
    if (now - slot.at > PREFETCH_TTL) prefetched.delete(key);
  }
  while (prefetched.size > PREFETCH_MAX) {
    const oldest = prefetched.keys().next();
    if (oldest.done) break;
    prefetched.delete(oldest.value);
  }
}

export function prefetchItem(id: string): void {
  const hit = prefetched.get(id);
  if (hit && Date.now() - hit.at < PREFETCH_TTL) return;
  prunePrefetch();
  const at = Date.now();
  const slot = prefetched.get(id) ?? { at };
  prefetched.set(id, slot);
  // 悬停预取只拉 /api/item：一屏慢扫过去，每条都连详情一起拉就是十二个请求
  // （详情里是正文 + 评论，最重的一份）。详情等真的点下去再拉。
  getJSON<ItemResponse>("/api/item/" + encodeURIComponent(id))
    .then((d) => {
      slot.item = d;
    })
    .catch(() => {
      /* 预取失败不用惊动用户，点进去会重新拉 */
    });
}

/** 真点下去之前先把详情排上队：转场本身要 420ms，这段时间正好盖住一次请求 */
export function prefetchDetail(id: string): void {
  const hit = prefetched.get(id);
  if (hit?.detail && Date.now() - hit.at < PREFETCH_TTL) return;
  const at = Date.now();
  const slot = prefetched.get(id) ?? { at };
  prefetched.set(id, slot);
  getDetail(id)
    .then((d) => {
      slot.detail = d;
    })
    .catch(() => {
      /* 同上 */
    });
}

/** 预取的结果只给首屏垫个底，过期就丢掉，别把旧内容当新内容用 */
export function peekItem(id: string): { item?: ItemResponse; detail?: DetailResponse } | null {
  const hit = prefetched.get(id);
  if (!hit || Date.now() - hit.at > PREFETCH_TTL) return null;
  return hit;
}

/** 详情一旦取到，一分钟内再进同一条就用这份：返回列表再点回来不该出现 7.9s 的冷启动 */
const detailCache = new Map<string, { at: number; value: DetailResponse }>();
const DETAIL_TTL = 60_000;

export function getDetail(id: string, refresh = false, signal?: AbortSignal): Promise<DetailResponse> {
  if (!refresh) {
    const hit = detailCache.get(id);
    if (hit && Date.now() - hit.at < DETAIL_TTL) return Promise.resolve(hit.value);
  }
  const qs = refresh ? "?refresh=1" : "";
  return getJSON<DetailResponse>("/api/item/" + encodeURIComponent(id) + "/detail" + qs, signal).then(
    (data) => {
      if (data && data.detail) {
        detailCache.set(id, { at: Date.now(), value: data });
        while (detailCache.size > 12) {
          const oldest = detailCache.keys().next();
          if (oldest.done) break;
          detailCache.delete(oldest.value);
        }
      }
      return data;
    },
  );
}

export interface SummaryPoint {
  text: string;
  /** 这条要点在原文里的秒数；没有时间轴时是 null */
  t: number | null;
}

export interface SummaryChapter {
  from?: number | null;
  title?: string;
}

/** 总结粒度。brief 只留骨架，detailed 写全话。 */
export type SummaryDepth = "brief" | "balanced" | "detailed";

export const SUMMARY_DEPTH_LABEL: Record<SummaryDepth, string> = {
  brief: "简洁",
  balanced: "平衡",
  detailed: "详细",
};

export interface SummaryPayload {
  tldr: string;
  points: SummaryPoint[];
  chapters?: SummaryChapter[];
  caveat?: string;
  /** 依据哪一档素材：完整字幕 / 平台自带总结 / 只有标题与简介 / 图片 */
  basis: "transcript" | "official" | "desc" | "visual" | string;
  basis_text?: string;
  duration?: number;
  engine: string;
  provider?: string;
  model?: string;
  source_chars: number;
  /** 真正送进模型的图片张数（0 或不填表示纯文本） */
  images?: number;
  ms: number;
  generated_at: number;
  note?: string;
  /** 这份总结是按哪一档粒度生成的；老缓存或规则兜底可能没有 */
  depth?: SummaryDepth | string;
}

export interface SummaryResponse {
  ok: boolean;
  summary?: SummaryPayload;
  from_cache?: boolean;
  fetched_at?: number;
  error?: string;
}

export function getSummary(id: string, refresh = false, signal?: AbortSignal): Promise<SummaryResponse> {
  const qs = refresh ? "?refresh=1" : "";
  return getJSON<SummaryResponse>("/api/item/" + encodeURIComponent(id) + "/summary" + qs, signal);
}
/** 流式总结的进度回调。done 之后调用方就不用再发请求了，整份 payload 会一起给到。 */
export interface SummaryStreamHandlers {
  onMeta?: (meta: { basis: string; basis_text?: string; duration?: number; source_chars?: number; images?: number }) => void;
  /** 推理型模型先想后写：收到一次 thinking 就够，用来把「卡住了」变成「在干活」 */
  onStatus?: (phase: string) => void;
  onDelta: (text: string) => void;
  onDone: (payload: SummaryPayload, fromCache: boolean) => void;
  onError: (message: string) => void;
}

/**
 * SSE 帧解析。总结和条目对话是同一套帧格式（data: {type,...}\n\n），
 * 所以只写一遍：谁用谁把事件翻译成自己的回调。
 */
async function pumpStream(
  resp: Response,
  signal: AbortSignal,
  onFrame: (frame: Record<string, unknown>) => void,
  onError: (message: string) => void,
): Promise<void> {
  const reader = resp.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let cut = buf.indexOf("\n\n");
      while (cut >= 0) {
        const chunk = buf.slice(0, cut);
        buf = buf.slice(cut + 2);
        cut = buf.indexOf("\n\n");
        for (const line of chunk.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const body = line.slice(5).trim();
          if (!body) continue;
          let frame: Record<string, unknown>;
          try {
            frame = JSON.parse(body) as Record<string, unknown>;
          } catch {
            continue; /* 坏帧丢掉，别因为一行解析失败把整段输出作废 */
          }
          onFrame(frame);
        }
      }
    }
  } catch (err) {
    if (!signal.aborted) onError(err instanceof Error ? err.message : "连接断了");
  }
}

/**
 * 流式总结。用 fetch 读 ReadableStream 而不是 EventSource：EventSource 收不到 404 的错误体，
 * 也没法 abort；猜错路径时用户只会看到「连接失败」，这里能给出具体原因。
 * depth 不传就由后端按设置页的默认档决定，回来时 payload.depth 会告诉我们用的是哪档。
 * 返回一个取消函数。
 */
export function streamSummary(
  id: string,
  refresh: boolean,
  h: SummaryStreamHandlers,
  depth?: SummaryDepth | "",
): () => void {
  // 静态演示站没有后端：别让用户等一个永远不会开始的流
  if (DEMO) {
    h.onError("静态演示站没有模型：总结要连 AI，本机运行才有。");
    return () => {};
  }
  const ctrl = new AbortController();
  const qs = new URLSearchParams();
  if (refresh) qs.set("refresh", "1");
  if (depth) qs.set("depth", depth);
  const suffix = qs.toString() ? "?" + qs.toString() : "";
  void (async () => {
    let resp: Response;
    try {
      resp = await fetch("/api/item/" + encodeURIComponent(id) + "/summary/stream" + suffix, {
        signal: ctrl.signal,
        headers: { Accept: "text/event-stream" },
      });
    } catch (err) {
      if (!ctrl.signal.aborted) h.onError(err instanceof Error ? err.message : "请求失败");
      return;
    }
    if (!resp.ok || !resp.body) {
      h.onError(resp.status === 404 ? "没有这条内容" : `请求失败（${resp.status}）`);
      return;
    }
    await pumpStream(
      resp,
      ctrl.signal,
      (frame) => {
        if (frame.type === "meta") h.onMeta?.(frame as never);
        else if (frame.type === "status") h.onStatus?.(String(frame.phase ?? ""));
        else if (frame.type === "delta") h.onDelta(String(frame.text ?? ""));
        else if (frame.type === "done") h.onDone(frame.summary as SummaryPayload, Boolean(frame.from_cache));
        else if (frame.type === "error") h.onError(String(frame.message ?? "生成失败"));
      },
      h.onError,
    );
  })();
  return () => ctrl.abort();
}

export interface PlatformHealth {
  platform: string;
  label: string;
  count: number;
  last_fetched_at: number;
  last_run_at: number;
  last_ok_at: number;
  /** 最近一次采集的成败；null = 没跑完 / 没跑过 */
  last_ok: boolean | null;
  failed: boolean;
  interrupted: boolean;
  stale: boolean;
  available: boolean;
  interval: number;
  /** ok / failed / stale / unavailable */
  state: "ok" | "failed" | "stale" | "unavailable" | string;
  running: boolean;
  error: string;
  note: string;
}

export interface Health {
  ok: boolean;
  version: string;
  items: number;
  db: string;
  plugins: number;
  platforms: PlatformHealth[];
  demo: boolean;
  refreshing: boolean;
  /** 插件目录读不动之类的全局错误；有内容要原样给用户看 */
  plugin_errors?: string[];
  /** failed + stale + unavailable 的平台数，顶栏据此常驻警示 */
  needs_attention?: number;
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
    // 带上 code：调用方要区分「已经在跑了」(refresh_running) 和真失败
    throw new ApiError(data?.detail?.message ?? `请求失败（${resp.status}）`,
      data?.detail?.code ?? "http_error");
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
  /** 只看收藏：AI 存的条目、手点星标的条目都在这一屏 */
  saved?: boolean;
}

// 详情页返回时首帧就要有卡片：共享元素变形需要一个真实的落点，
// 顺便也省掉一次「白屏然后重排」。
const feedCache = new Map<string, FeedResponse>();

export function useFeed(query: FeedQuery, reloadKey: number) {
  const cacheKey = JSON.stringify([
    query.platforms,
    query.kind,
    query.sort,
    query.q,
    query.since ?? 0,
    query.saved ? 1 : 0,
  ]);
  const seed = feedCache.get(cacheKey);
  const [items, setItems] = useState<FeedItem[]>(() => seed?.items ?? []);
  const [next, setNext] = useState<string | null>(() => seed?.next ?? null);
  const [count, setCount] = useState(() => seed?.count ?? 0);
  const [parsed, setParsed] = useState<ParsedQuery | null>(() => seed?.parsed ?? null);
  const [loading, setLoading] = useState(!seed);
  // 下一页单独一套状态：自动预取时不能把首屏的「正在取内容…」再翻出来，
  // 也不能让列表底部那块占位忽有忽无（整页会跟着抖）。
  const [moreLoading, setMoreLoading] = useState(false);
  const [error, setError] = useState("");
  const abortRef = useRef<AbortController | null>(null);
  // 单飞：滚动传感器可能在一次请求飞在路上时又触发一次，重复请求会把同一页追两遍
  const flight = useRef(false);
  // 这一屏数据到底是哪个 reloadKey 取回来的：刷新演出必须等它，否则会拿着
  // 上一批条目算「新增」，要么演出没东西可演，要么把老条目当新条目弹一遍。
  const keyRef = useRef(reloadKey);
  keyRef.current = reloadKey;
  const [loadedKey, setLoadedKey] = useState<number | null>(seed ? reloadKey : null);

  const build = useCallback(
    (cursor: string | null) => {
      const params = new URLSearchParams();
      if (query.platforms.length) params.set("platform", query.platforms.join(","));
      if (query.kind) params.set("kind", query.kind);
      if (query.sort) params.set("sort", query.sort);
      if (query.q.trim()) params.set("q", query.q.trim());
      if (query.since) params.set("since", String(query.since));
      if (query.saved) params.set("saved", "1");
      if (cursor) params.set("cursor", cursor);
      // 一页 18 条：实测一次追加 30 张卡是 226ms 帧 + 191ms 长任务，
      // 18 条时挂载/图片解码都摊薄了，滚到底还是两三屏的量。
      params.set("limit", "18");
      return "/api/feed?" + params.toString();
    },
    [query.platforms.join(","), query.kind, query.sort, query.q, query.since ?? 0, query.saved ? 1 : 0],
  );

  const load = useCallback(
    async (cursor: string | null, append: boolean) => {
      if (flight.current) return;
      flight.current = true;
      // 追加时不能 abort：那是把正在飞的那一页丢掉再要一次，尾巴会被截断
      if (!append) abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      if (append) setMoreLoading(true);
      else setLoading(true);
      setError("");
      try {
        const data = await getJSON<FeedResponse>(build(cursor), controller.signal);
        if (!append) {
          feedCache.set(cacheKey, data);
          // 筛选条件一路换下去，这张表会长得没有边；留最近 20 种组合足够。
          while (feedCache.size > 20) {
            const oldest = feedCache.keys().next();
            if (oldest.done) break;
            feedCache.delete(oldest.value);
          }
        }
        // 星标是 per-item 的外部仓库：列表数据一到就把它灌进去，
        // 否则第一次点星标会按「没存过」算，把已存的条目又存一遍
        seedSaved(data.items);
        setItems((prev) => {
          if (!append) return data.items;
          // 游标是稳定的，但刷新一轮后条目可能移位；按 id 去重，
          // 免得同一张卡在列表里出现两次（React key 重了会直接报错）
          const seen = new Set(prev.map((entry) => entry.id));
          return [...prev, ...data.items.filter((entry) => !seen.has(entry.id))];
        });
        setNext(data.next);
        setCount(data.count);
        setParsed(data.parsed);
      } catch (err) {
        if ((err as Error).name !== "AbortError") setError((err as Error).message);
      } finally {
        flight.current = false;
        if (!append) setLoadedKey(keyRef.current);
        setMoreLoading(false);
        setLoading(false);
      }
    },
    [build, cacheKey],
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
    loadedKey,
    moreLoading,
    error,
    more: () => (next ? load(next, true) : Promise.resolve()),
  };
}