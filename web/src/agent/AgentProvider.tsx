import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  agentAnswer,
  agentCancel,
  agentConfirm,
  agentSave,
  agentStart,
  agentStream,
  aiChat,
  ApiError,
  getThread,
  listThreads,
  type AgentEvent,
  type AgentThread,
  type AiResponse,
  type FeedItem,
} from "../api";
import { createGhost } from "../motion/ghost";
import { runNav } from "../motion/nav";
import { popScope, pushScope, useHotkeys } from "../motion/useHotkeys";

/* ------------------------------------------------------------------ 类型 */

export interface AgentTurn {
  role: "user" | "ai";
  text: string;
  data?: AiResponse;
  trace?: AgentEvent[];
  stopped?: boolean;
  /** 从历史里回放出来的一轮：轨迹只读，不再等你确认或回答 */
  history?: boolean;
}

/** 详情页告诉 Agent「用户正看着这一条」，问「总结这条」时不用再问是哪条 */
export interface AgentFocus {
  id: string;
  title: string;
  platform: string;
}

export interface AgentSessionState {
  turns: AgentTurn[];
  busy: boolean;
  live: { run_id: string; events: AgentEvent[] } | null;
  answered: Record<string, boolean>;
  answeredAsk: Record<string, string[]>;
  stopping: boolean;
  threadId: string;
  saved: Set<string>;
  error: string;
}

export interface AgentSurfaceState {
  open: boolean;
  /** closed：只剩唤起器；sheet：底部抽屉；rail：右栏（App 外壳的右槽位渲染） */
  mode: "closed" | "sheet" | "rail";
  wide: boolean;
  /** ≥1800 时右栏常驻：详情页的唤起器收起来，不跟常驻的右栏重复 */
  pinned: boolean;
  onItemPage: boolean;
  onAgentPage: boolean;
  focus: AgentFocus | null;
  hintIndex: number;
  draft: string;
}

export interface AgentActions {
  setOpen: (open: boolean) => void;
  openWith: (prefill?: string) => void;
  close: () => void;
  ask: (message: string, exclude?: string[]) => void;
  stop: () => void;
  confirm: (confirmId: string, allow: boolean) => void;
  answer: (askId: string, selected: string[], text: string) => void;
  toggleSave: (id: string) => void;
  applyFilter: (data: AiResponse) => void;
  toggleHistory: () => void;
  /** 无条件打开并拉一次会话史：抽屉 / 右栏的历史面板用 */
  loadHistory: () => void;
  /** 只刷新列表，不动历史面板的开合：左右侧的常驻栏用它 */
  refreshHistory: () => Promise<void>;
  resumeThread: (thread: AgentThread) => void;
  newThread: () => void;
  setFocus: (focus: AgentFocus | null) => void;
  openItem: (id: string, seed?: FeedItem) => void;
  setDraft: (text: string) => void;
  inputRef: RefObject<HTMLInputElement>;
}

/* ------------------------------------------------------------------ 上下文 */

const SessionCtx = createContext<AgentSessionState | null>(null);
const SurfaceCtx = createContext<AgentSurfaceState | null>(null);
const ActionsCtx = createContext<AgentActions | null>(null);
const HistoryCtx = createContext<{
  open: boolean;
  items: AgentThread[];
  loading: boolean;
} | null>(null);

export function useAgentSession(): AgentSessionState {
  const value = useContext(SessionCtx);
  if (!value) throw new Error("useAgentSession 要在 AgentProvider 里用");
  return value;
}

export function useAgentSurface(): AgentSurfaceState {
  const value = useContext(SurfaceCtx);
  if (!value) throw new Error("useAgentSurface 要在 AgentProvider 里用");
  return value;
}

export function useAgentActions(): AgentActions {
  const value = useContext(ActionsCtx);
  if (!value) throw new Error("useAgentActions 要在 AgentProvider 里用");
  return value;
}

export function useAgentHistory() {
  const value = useContext(HistoryCtx);
  if (!value) throw new Error("useAgentHistory 要在 AgentProvider 里用");
  return value;
}

/* ------------------------------------------------------------------ 工具 */

const THREAD_KEY = "onefeed.agent.thread";
const HINTS = [
  "今天 B 站有什么值得看的 AI 内容",
  "随便来点，别老是同一个平台",
  "把这周热度最高的几条挑出来",
];

function readThread(): string {
  try {
    return window.localStorage.getItem(THREAD_KEY) ?? "";
  } catch {
    return "";
  }
}

/** 从筛选条件拼回首页的查询串：Agent 在详情页也能把信息流切过去 */
function filterQuery(detail: { platforms?: string[]; keyword?: string; range?: string; sort?: string }): string {
  const sp = new URLSearchParams();
  if (detail.platforms?.length) sp.set("p", detail.platforms.join(","));
  if (detail.keyword) sp.set("q", detail.keyword);
  if (detail.range === "today") sp.set("range", "today");
  if (detail.sort) sp.set("sort", detail.sort);
  return sp.toString();
}

/* ------------------------------------------------------------------ Provider */

export function AgentProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useLocation();

  const onItemPage = location.pathname.startsWith("/item/");
  const onAgentPage = location.pathname === "/agent" || location.pathname.startsWith("/agent/");

  /* 会话：切换形态、换页面都不重建 */
  const [turns, setTurns] = useState<AgentTurn[]>([]);
  const [busy, setBusy] = useState(false);
  const [live, setLive] = useState<{ run_id: string; events: AgentEvent[] } | null>(null);
  const [answered, setAnswered] = useState<Record<string, boolean>>({});
  const [answeredAsk, setAnsweredAsk] = useState<Record<string, string[]>>({});
  const [stopping, setStopping] = useState(false);
  const [threadId, setThreadId] = useState(readThread);
  const [saved, setSaved] = useState<Set<string>>(() => new Set());
  const [error, setError] = useState("");

  /* 形态 */
  const [open, setOpen] = useState(false);
  const [focus, setFocusState] = useState<AgentFocus | null>(null);
  const [draft, setDraft] = useState("");
  const [hintIndex, setHintIndex] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyItems, setHistoryItems] = useState<AgentThread[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [wide, setWide] = useState(() =>
    typeof window === "undefined" ? true : window.matchMedia("(min-width: 1080px)").matches,
  );
  const [pinned, setPinned] = useState(() =>
    typeof window === "undefined" ? false : window.matchMedia("(min-width: 1800px)").matches,
  );

  const streamRef = useRef<(() => void) | null>(null);
  const settledRef = useRef(false);
  const cancelledRef = useRef(false);
  const stopTimerRef = useRef<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const setThread = useCallback((id: string) => {
    setThreadId(id);
    try {
      if (id) window.localStorage.setItem(THREAD_KEY, id);
      else window.localStorage.removeItem(THREAD_KEY);
    } catch {
      /* 隐私模式下写不进去就算了，这一轮还能用 */
    }
  }, []);

  const clearStopTimer = useCallback(() => {
    if (stopTimerRef.current !== null) {
      window.clearTimeout(stopTimerRef.current);
      stopTimerRef.current = null;
    }
  }, []);

  /* 宽度决定详情页给不给右栏；窄屏一律用底部抽屉 */
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1080px)");
    const on = () => setWide(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  /* 1800 起右栏常驻在栅格里（见 layout/useShell.ts），唤起器要让位 */
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1800px)");
    const on = () => setPinned(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);

  /* 占位提示每 4s 换一句：第一次打开就有东西可点，不用现想 */
  useEffect(() => {
    const timer = window.setInterval(() => setHintIndex((i) => (i + 1) % HINTS.length), 4000);
    return () => window.clearInterval(timer);
  }, []);

  const say = useCallback((text: string) => {
    setTurns((prev) => [...prev, { role: "ai", text }]);
  }, []);

  // 「从对话里打开一条」和「点卡片」走的是同一套共享元素转场，区别只在起点：
  // 卡片在页面上就直接用它的媒体框／标题；不在（Agent 自己找出来的条目）就补一个右侧代位盒子，
  // 于是视频照样从右侧长出来，而不是整页淡出。
  const openItem = useCallback(
    (id: string, seed?: FeedItem) => {
      const from = location.pathname + location.search;
      const card = Array.from(document.querySelectorAll<HTMLElement>("[data-vt-item]")).find(
        (el) => el.getAttribute("data-vt-item") === id,
      );
      const media = card?.querySelector<HTMLElement>('[data-vt="media"]') ?? null;
      const title = card?.querySelector<HTMLElement>('[data-vt="title"]') ?? null;
      const ghost = card ? null : createGhost({ media: true, title: true });
      ghost?.mount();
      runNav(
        "push",
        () => {
          // 旧快照已经拍完了，代位盒子在这里摘掉：留到新快照就会和新页面上的共享元素同名，
          // 浏览器会整段取消转场（控制台报 duplicate view-transition-name）。
          ghost?.remove();
          navigate("/item/" + encodeURIComponent(id), {
            // item 作为详情页的首屏种子：没有它新页面先渲染骨架，骨架里没有媒体框，
            // 共享元素就少了一半，转场会退回整页淡出。
            state: { vt: true, from, fromId: id, fromAgent: true, item: seed },
          });
        },
        {
          names: card
            ? [
                { el: media, name: "of-media" },
                { el: title, name: "of-title" },
              ]
            : [],
          after: () => ghost?.remove(),
        },
      );
      if (!wide) setOpen(false);
    },
    [location.pathname, location.search, navigate, wide],
  );

  /** 当前这轮结果里的条目：Agent 打开时拿它当详情页首屏种子，转场才有媒体框可接 */
  const turnsRef = useRef<AgentTurn[]>([]);
  useEffect(() => {
    turnsRef.current = turns;
  }, [turns]);

  const applyUi = useCallback(
    (event: AgentEvent) => {
      const payload = (event.data?.payload ?? {}) as Record<string, unknown>;
      if (event.name === "ui_filter") {
        const detail = {
          platforms: Array.isArray(payload.platforms) ? payload.platforms.map(String) : [],
          keyword: typeof payload.keyword === "string" ? payload.keyword : "",
          range: payload.since === "today" ? "today" : "all",
          sort: typeof payload.sort === "string" ? payload.sort : undefined,
        };
        window.dispatchEvent(new CustomEvent("onefeed:filter", { detail }));
        if (location.pathname !== "/") {
          const qs = filterQuery(detail);
          navigate(qs ? "/?" + qs : "/", { state: { vt: true } });
        }
      } else if (event.name === "ui_open_item" && payload.id) {
        const id = String(payload.id);
        // Agent 自己走到一条内容上：跟点卡片走同一套转场（信息流里有卡就用卡，
        // 没有就用右侧代位盒子），种子从这一轮的结果里取，详情页首屏立刻有媒体框。
        const seed = turnsRef.current
          .flatMap((t) => t.data?.items ?? [])
          .find((it) => it.id === id);
        openItem(id, seed);
      }
    },
    [openItem],
  );

  /** 收尾：done 与 cancelled 共用一份 payload 组装，只差一句文案与标记 */
  const settle = useCallback(
    (event: AgentEvent, stopped: boolean, trace: AgentEvent[]) => {
      settledRef.current = true;
      streamRef.current?.();
      streamRef.current = null;
      clearStopTimer();
      setError("");
      const d = (event.data ?? {}) as Record<string, unknown>;
      const items: FeedItem[] = Array.isArray(d.items) ? (d.items as FeedItem[]) : [];
      const usage = (d.usage ?? {}) as Record<string, unknown>;
      const data: AiResponse = {
        engine: "agent",
        provider: typeof d.provider === "string" ? d.provider : "",
        plan:
          (d.plan as AiResponse["plan"]) ??
          { mode: "agent", platforms: [], kinds: [], since: null, keyword: "", sort: "freshness" },
        reply: String(d.reply ?? ""),
        items,
        count: items.length,
        suggestions: Array.isArray(d.suggestions) ? (d.suggestions as string[]) : [],
        understood: String(d.understood ?? ""),
        steps: Number(usage.steps ?? 0),
        ms: Number(usage.ms ?? 0),
      };
      setTurns((prev) => [
        ...prev,
        {
          role: "ai",
          text: data.reply || (stopped ? "停下了。" : `翻到 ${items.length} 条。`),
          data,
          trace,
          stopped,
        },
      ]);
      // 回来带 saved 标记的条目：结果行上的星标一开始就得是实心的
      const marked = items.filter((item) => item.saved).map((item) => item.id);
      if (marked.length) {
        setSaved((prev) => {
          const next = new Set(prev);
          for (const id of marked) next.add(id);
          return next;
        });
      }
      setLive(null);
      setBusy(false);
      setStopping(false);
      cancelledRef.current = false;
    },
    [clearStopTimer],
  );

  const listen = useCallback(
    (runId: string) => {
      const events: AgentEvent[] = [];
      settledRef.current = false;
      cancelledRef.current = false;
      setAnswered({});
      // 不回滚 answeredAsk：上一轮回过的问卷要保持「你回了」，否则历史里的选项会重新变可点
      setLive({ run_id: runId, events: [] });
      streamRef.current?.();
      streamRef.current = agentStream(
        runId,
        (event) => {
          events.push(event);
          setLive({ run_id: runId, events: [...events] });
          if (event.kind === "action") applyUi(event);
          if (event.kind === "done") settle(event, false, events.slice());
          else if (event.kind === "cancelled") settle(event, true, events.slice());
        },
        (msg) => {
          if (settledRef.current) return;
          settledRef.current = true;
          streamRef.current = null;
          clearStopTimer();
          setLive(null);
          setBusy(false);
          setStopping(false);
          if (cancelledRef.current) {
            // 叫停时后端本来就会关流：这是预期，不该报「事件流断了」
            cancelledRef.current = false;
            setTurns((prev) => [...prev, { role: "ai", text: "停下了。", stopped: true }]);
            return;
          }
          setError(msg);
          say(`${msg}，稍后再试。`);
        },
      );
    },
    [applyUi, clearStopTimer, say, settle],
  );

  const fallback = useCallback(
    async (said: string, exclude: string[], history: unknown) => {
      try {
        const data = await aiChat(said, { exclude, history });
        setTurns((prev) => [...prev, { role: "ai", text: data.reply, data }]);
      } catch (err) {
        say(err instanceof Error ? err.message : "请求失败");
      } finally {
        setBusy(false);
      }
    },
    [say],
  );

  const ask = useCallback(
    async (message: string, exclude: string[] = []) => {
      const said = message.trim();
      if (!said || busy) return;
      setDraft("");
      setOpen(true);
      clearStopTimer();
      cancelledRef.current = false;
      setStopping(false);
      setBusy(true);
      setError("");
      setTurns((prev) => [...prev, { role: "user", text: said }]);
      const history = turns.slice(-4).map((turn) => ({
        role: turn.role === "user" ? "user" : "assistant",
        text: turn.text,
        plan: turn.data?.plan,
      }));
      try {
        const started = await agentStart(said, {
          exclude,
          history,
          thread_id: threadId || undefined,
          context: focus ? { item_id: focus.id, title: focus.title, platform: focus.platform } : undefined,
        });
        if (started.thread_id) setThread(started.thread_id);
        listen(started.run_id);
      } catch (err) {
        // 后端关掉 Agent 或旧版本没有这条路由：退回一次出计划的老路径
        if (err instanceof ApiError && (err.code === "agent_unavailable" || err.code === "http_error")) {
          await fallback(said, exclude, history);
          return;
        }
        say(err instanceof Error ? err.message : "请求失败");
        setBusy(false);
      }
    },
    [busy, clearStopTimer, fallback, focus, listen, say, setThread, threadId, turns],
  );

  const confirm = useCallback(
    async (confirmId: string, allow: boolean) => {
      if (!live) return;
      setAnswered((prev) => ({ ...prev, [confirmId]: allow }));
      try {
        await agentConfirm(live.run_id, confirmId, allow);
      } catch {
        /* 过期了就按后端拒绝处理，不打扰用户 */
      }
    },
    [live],
  );

  /** 回 Agent 的提问：选选项、或直接说一句，都走这一条路 */
  const answer = useCallback(
    async (askId: string, selected: string[], text: string) => {
      if (!live) return;
      const show = selected.length ? selected : text ? [text] : [];
      setAnsweredAsk((prev) => ({ ...prev, [askId]: show }));
      try {
        await agentAnswer(live.run_id, askId, selected, text);
        inputRef.current?.focus();
      } catch {
        say("这条提问已经收尾了，我把这轮留给你，重新说一句就行。");
      }
    },
    [live, say],
  );

  const toggleSave = useCallback(async (id: string) => {
    const on = !saved.has(id);
    setSaved((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
    try {
      await agentSave(id, on);
      // 稍后再看那份列表跟卡片星标是同一份数据，改完广播一下让它自己刷新
      window.dispatchEvent(new CustomEvent("onefeed:saved", { detail: { id, saved: on } }));
    } catch {
      setSaved((prev) => {
        const next = new Set(prev);
        if (on) next.delete(id);
        else next.add(id);
        return next;
      });
    }
  }, [saved]);

  const refreshHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const data = await listThreads(20);
      setHistoryItems(data.threads ?? []);
    } catch {
      setHistoryItems([]);
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setHistoryOpen(true);
    await refreshHistory();
  }, [refreshHistory]);

  const toggleHistory = useCallback(async () => {
    if (historyOpen) {
      setHistoryOpen(false);
      return;
    }
    await loadHistory();
  }, [historyOpen, loadHistory]);

  /** 接着上一段聊：把历史问答连同结果卡片、轨迹一起铺回来，再发消息就落进同一条线程 */
  const resumeThread = useCallback(
    async (thread: AgentThread) => {
      try {
        const data = await getThread(thread.id);
        const next: AgentTurn[] = [];
        const marked: string[] = [];
        for (const run of data.runs ?? []) {
          if (run.input) next.push({ role: "user", text: run.input });
          const events = Array.isArray(run.events) ? run.events : [];
          // 回放跟实时同形：轨迹照铺，只把流式正文的 delta 丢掉（几十帧、没有展示价值）
          const trace = events.filter((event) => event.kind !== "delta");
          const final = [...events]
            .reverse()
            .find((event) => event.kind === "done" || event.kind === "cancelled");
          if (!final) {
            const text = run.reply || (run.status === "error" ? "这一轮没跑完。" : "");
            if (text) {
              next.push({
                role: "ai",
                text,
                trace: trace.length ? trace : undefined,
                history: true,
              });
            }
            continue;
          }
          const d = (final.data ?? {}) as Record<string, unknown>;
          const items: FeedItem[] = Array.isArray(d.items) ? (d.items as FeedItem[]) : [];
          const usage = (d.usage ?? {}) as Record<string, unknown>;
          const stopped = run.status === "cancelled" || final.kind === "cancelled";
          const reply = String(d.reply ?? run.reply ?? "");
          const ai: AiResponse = {
            engine: "agent",
            provider: typeof d.provider === "string" ? d.provider : "",
            plan:
              (d.plan as AiResponse["plan"]) ??
              { mode: "agent", platforms: [], kinds: [], since: null, keyword: "", sort: "freshness" },
            reply,
            items,
            count: items.length,
            suggestions: Array.isArray(d.suggestions) ? (d.suggestions as string[]) : [],
            understood: String(d.understood ?? ""),
            steps: Number(usage.steps ?? run.steps ?? 0),
            ms: Number(usage.ms ?? run.ms ?? 0),
          };
          for (const item of items) if (item.saved) marked.push(item.id);
          next.push({
            role: "ai",
            text: reply || (stopped ? "停下了。" : `翻到 ${items.length} 条。`),
            data: ai,
            trace: trace.length ? trace : undefined,
            stopped,
            history: true,
          });
        }
        setTurns(next);
        if (marked.length) {
          setSaved((prev) => {
            const merged = new Set(prev);
            for (const id of marked) merged.add(id);
            return merged;
          });
        }
        setThread(thread.id);
        setHistoryOpen(false);
        setOpen(true);
      } catch {
        say("这段对话没读到，稍后再试。");
      }
    },
    [say, setThread],
  );

  const newThread = useCallback(() => {
    setTurns([]);
    setThread("");
    setHistoryOpen(false);
    setOpen(true);
    setError("");
    inputRef.current?.focus();
  }, [setThread]);

  const stop = useCallback(async () => {
    if (!live || stopping) return;
    cancelledRef.current = true;
    setStopping(true);
    // 兜底：后端线程可能正卡在一次模型请求里，SSE 迟迟不关时不至于让按钮一直转
    clearStopTimer();
    stopTimerRef.current = window.setTimeout(() => {
      settledRef.current = true;
      streamRef.current?.();
      streamRef.current = null;
      setLive(null);
      setBusy(false);
      setStopping(false);
      cancelledRef.current = false;
      say("停下了。");
    }, 8000);
    try {
      const res = await agentCancel(live.run_id);
      if (!res.ok) {
        // 停止位没置上 = 这轮早结束了
        clearStopTimer();
        cancelledRef.current = false;
        setStopping(false);
        setBusy(false);
        setLive(null);
        say("这轮已经结束了。");
      }
    } catch {
      clearStopTimer();
      cancelledRef.current = false;
      setStopping(false);
      say("没能叫停，稍后再试。");
    }
  }, [clearStopTimer, live, say, stopping]);

  const applyFilter = useCallback(
    (data: AiResponse) => {
      // plan.since 是检索时真实生效的起始秒；只有落在 36 小时内的才算「今天」
      const since = Number(data.plan.since || 0);
      const detail = {
        platforms: data.plan.platforms,
        keyword: data.plan.keyword,
        range: (since && Date.now() / 1000 - since <= 36 * 3600 ? "today" : "all") as "today" | "all",
        sort: data.plan.sort,
      };
      if (location.pathname === "/") {
        // 已经在信息流：交给页面改 URL，不产生一次多余的整页跳转
        window.dispatchEvent(new CustomEvent("onefeed:filter", { detail }));
      } else {
        const qs = filterQuery(detail);
        navigate(qs ? "/?" + qs : "/", { state: { vt: true } });
      }
      if (!wide) setOpen(false);
    },
    [location.pathname, navigate, wide],
  );

  const close = useCallback(() => {
    const active = document.activeElement;
    if (active instanceof HTMLElement && document.querySelector('[data-agent-surface="sheet"]')?.contains(active)) {
      inputRef.current?.focus();
    }
    if (!open) {
      setOpen(false);
      return;
    }
    // 详情页右栏（≥1080）：右栏是常驻槽位的一部分，收起只是把 tab 还给「稍后再看」，
    // 不做缩回唤起器的转场 —— 那里没有唤起器可缩。
    if (onItemPage && wide) {
      setOpen(false);
      return;
    }
    // 收起方向：抽屉缩回唤起器。唤起器是收起之后才挂上的，新快照里没有它，
    // 所以代位盒子要挂在 apply 里 —— 那样它只进新快照，正好当终点。
    const ghost = createGhost({ agent: onItemPage && wide ? "corner" : "pill" });
    runNav(
      "back",
      () => {
        ghost.mount();
        setOpen(false);
      },
      { after: () => ghost.remove() },
    );
  }, [open, onItemPage, wide]);

  const openWith = useCallback(
    (prefill?: string) => {
      if (typeof prefill === "string") setDraft(prefill);
      if (open) {
        window.setTimeout(() => inputRef.current?.focus(), 30);
        return;
      }
      // 打开方向：唤起器还在旧快照里但没有名字，给它挂个代位盒子，抽屉就从它的位置长出来。
      const ghost = createGhost({ agent: onItemPage && wide ? "corner" : "pill" });
      ghost.mount();
      runNav(
        "tab",
        () => {
          // 同上：这个盒子只属于旧快照（唤起器的位置），apply 一开始就摘，别带进新快照
          ghost.remove();
          setOpen(true);
        },
        { after: () => ghost.remove() },
      );
      window.setTimeout(() => inputRef.current?.focus(), 30);
    },
    [open, onItemPage, wide],
  );

  const setFocus = useCallback((next: AgentFocus | null) => setFocusState(next), []);

  /* 全站快捷键 / 唤起事件：面板打开时 Esc 收起 */
  useEffect(() => {
    const onAsk = () => {
      setOpen(true);
      window.setTimeout(() => inputRef.current?.focus(), 30);
    };
    window.addEventListener("onefeed:ask", onAsk);
    return () => window.removeEventListener("onefeed:ask", onAsk);
  }, []);

  useEffect(() => {
    if (!open) return;
    pushScope("dialog");
    return () => popScope("dialog");
  }, [open]);

  useHotkeys("dialog", { escape: close }, open);

  /* 卸载时别把 SSE 和停止兜底定时器留在后台 */
  useEffect(
    () => () => {
      streamRef.current?.();
      clearStopTimer();
    },
    [clearStopTimer],
  );

  const mode: AgentSurfaceState["mode"] = !open
    ? "closed"
    : onItemPage && wide
      ? "rail"
      : "sheet";

  const session = useMemo<AgentSessionState>(
    () => ({ turns, busy, live, answered, answeredAsk, stopping, threadId, saved, error }),
    [turns, busy, live, answered, answeredAsk, stopping, threadId, saved, error],
  );

  const surface = useMemo<AgentSurfaceState>(
    () => ({ open, mode, wide, pinned, onItemPage, onAgentPage, focus, hintIndex, draft }),
    [open, mode, wide, pinned, onItemPage, onAgentPage, focus, hintIndex, draft],
  );

  const actions = useMemo<AgentActions>(
    () => ({
      setOpen,
      openWith,
      close,
      ask,
      stop,
      confirm,
      answer,
      toggleSave,
      applyFilter,
      toggleHistory,
      loadHistory,
      refreshHistory,
      resumeThread,
      newThread,
      setFocus,
      openItem,
      setDraft,
      inputRef,
    }),
    [
      openWith,
      close,
      ask,
      stop,
      confirm,
      answer,
      toggleSave,
      applyFilter,
      toggleHistory,
      loadHistory,
      refreshHistory,
      resumeThread,
      newThread,
      setFocus,
      openItem,
    ],
  );

  const history = useMemo(
    () => ({ open: historyOpen, items: historyItems, loading: historyLoading }),
    [historyOpen, historyItems, historyLoading],
  );

  return (
    <SessionCtx.Provider value={session}>
      <SurfaceCtx.Provider value={surface}>
        <ActionsCtx.Provider value={actions}>
          <HistoryCtx.Provider value={history}>{children}</HistoryCtx.Provider>
        </ActionsCtx.Provider>
      </SurfaceCtx.Provider>
    </SessionCtx.Provider>
  );
}

export { HINTS };
