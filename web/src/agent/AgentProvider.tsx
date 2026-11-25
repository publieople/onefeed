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
import { savedStore } from "./savedStore";
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
  /** 后台还在跑的会话 id：切走以后也能一眼看出哪段没停 */
  running?: string[];
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

function mintThreadId(): string {
  try {
    return crypto.randomUUID();
  } catch {
    return "t" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
  }
}

type SessionCore = {
  turns: AgentTurn[];
  busy: boolean;
  live: { run_id: string; events: AgentEvent[] } | null;
  answered: Record<string, boolean>;
  answeredAsk: Record<string, string[]>;
  stopping: boolean;
  threadId: string;
  error: string;
};

function blankSession(key: string): SessionCore {
  return {
    turns: [],
    busy: false,
    live: null,
    answered: {},
    answeredAsk: {},
    stopping: false,
    threadId: key,
    error: "",
  };
}

type StreamCtl = {
  close: (() => void) | null;
  runId: string;
  settled: boolean;
  cancelled: boolean;
  flush: number;
  timer: number | null;
};

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

  /* 会话：每条线程一份状态。
     以前只有一份 turns/busy/live，切走之后旧轮的事件会写进新会话，停止也只能停眼前这条。
     现在每个线程各自收事件，切走只是把 activeKey 换掉，后台那轮照跑。 */
  const initialKey = useRef(readThread() || mintThreadId());
  const [threadId, setThreadId] = useState(initialKey.current);
  const [sessions, setSessions] = useState<Record<string, SessionCore>>(() => ({
    [initialKey.current]: blankSession(initialKey.current),
  }));
  const activeKeyRef = useRef(initialKey.current);
  const sessionsRef = useRef(sessions);
  const [saved, setSaved] = useState<Set<string>>(() => new Set());

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

  /** 每条线程最多一条 SSE；key 是线程 id，后台线程的事件只写到自己那份 */
  const streamsRef = useRef<Map<string, StreamCtl>>(new Map());
  const resumeToken = useRef(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    activeKeyRef.current = threadId;
  }, [threadId]);
  useEffect(() => {
    sessionsRef.current = sessions;
  }, [sessions]);

  const patchSession = useCallback((key: string, update: (s: SessionCore) => SessionCore) => {
    setSessions((prev) => {
      const current = prev[key] ?? blankSession(key);
      const next = update(current);
      if (next === current) return prev;
      return { ...prev, [key]: next };
    });
  }, []);

  const patchActive = useCallback(
    (update: (s: SessionCore) => SessionCore) => patchSession(activeKeyRef.current, update),
    [patchSession],
  );

  const setAnswered = useCallback(
    (value: Record<string, boolean> | ((prev: Record<string, boolean>) => Record<string, boolean>)) =>
      patchActive((s) => ({ ...s, answered: typeof value === "function" ? value(s.answered) : value })),
    [patchActive],
  );
  const setAnsweredAsk = useCallback(
    (value: Record<string, string[]> | ((prev: Record<string, string[]>) => Record<string, string[]>)) =>
      patchActive((s) => ({ ...s, answeredAsk: typeof value === "function" ? value(s.answeredAsk) : value })),
    [patchActive],
  );
  const setThread = useCallback(
    (id: string) => {
      if (!id) return;
      setThreadId(id);
      activeKeyRef.current = id;
      setSessions((prev) => (prev[id] ? prev : { ...prev, [id]: blankSession(id) }));
      try {
        window.localStorage.setItem(THREAD_KEY, id);
      } catch {
        /* 隐私模式下写不进去就算了，这一轮还能用 */
      }
    },
    [],
  );

  const clearStopTimer = useCallback((key = activeKeyRef.current) => {
    const ctl = streamsRef.current.get(key);
    if (ctl?.timer != null) {
      window.clearTimeout(ctl.timer);
      ctl.timer = null;
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

  const sayTo = useCallback(
    (key: string, text: string) => patchSession(key, (s) => ({ ...s, turns: [...s.turns, { role: "ai", text }] })),
    [patchSession],
  );
  const say = useCallback((text: string) => sayTo(activeKeyRef.current, text), [sayTo]);

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

  const applyUi = useCallback(
    (event: AgentEvent, key: string) => {
      // 后台线程的 UI 动作不能劫持前台：它只是没人看的时候继续把活干完
      if (key !== activeKeyRef.current) return;
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
        const seed = (sessionsRef.current[key]?.turns ?? [])
          .flatMap((t) => t.data?.items ?? [])
          .find((it) => it.id === id);
        openItem(id, seed);
      }
    },
    [openItem],
  );

  /** 收尾：done 与 cancelled 共用一份 payload 组装，只差一句文案与标记 */
  const settle = useCallback(
    (event: AgentEvent, stopped: boolean, trace: AgentEvent[], key: string) => {
      const ctl = streamsRef.current.get(key);
      if (ctl) {
        if (ctl.settled) return;
        ctl.settled = true;
        if (ctl.flush) window.cancelAnimationFrame(ctl.flush);
        ctl.close?.();
        ctl.close = null;
        ctl.timer = null;
      }
      clearStopTimer(key);
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
      patchSession(key, (s) => ({
        ...s,
        turns: [
          ...s.turns,
          {
            role: "ai",
            text: data.reply || (stopped ? "停下了。" : `翻到 ${items.length} 条。`),
            data,
            trace,
            stopped,
          },
        ],
        live: null,
        busy: false,
        stopping: false,
        error: "",
      }));
      // 回来带 saved 标记的条目：结果行上的星标一开始就得是实心的
      const marked = items.filter((item) => item.saved).map((item) => item.id);
      for (const id of marked) savedStore.set(id, true);
      if (marked.length) {
        setSaved((prev) => {
          const next = new Set(prev);
          for (const id of marked) next.add(id);
          return next;
        });
      }
      if (ctl) ctl.cancelled = false;
      streamsRef.current.delete(key);
    },
    [clearStopTimer, patchSession],
  );

  const listen = useCallback(
    (runId: string, key: string) => {
      // 同一线程只留一条流：重连/重发时先关旧的，别让两份事件往同一份状态里写
      streamsRef.current.get(key)?.close?.();
      const ctl: StreamCtl = { close: null, runId, settled: false, cancelled: false, flush: 0, timer: null };
      streamsRef.current.set(key, ctl);
      const events: AgentEvent[] = [];
      // 一帧最多把轨迹同步给界面一次。之前每个事件都 [...events] 复制整份数组，
      // 一轮 30 个事件就是 465 次拷贝 + 30 次重渲染，长任务一半花在这上面。
      const scheduleFlush = () => {
        if (ctl.flush) return;
        ctl.flush = window.requestAnimationFrame(() => {
          ctl.flush = 0;
          if (ctl.settled) return;
          patchSession(key, (s) => ({ ...s, live: { run_id: runId, events: events.slice() } }));
        });
      };
      patchSession(key, (s) => ({ ...s, answered: {}, live: { run_id: runId, events: [] } }));
      // 不回滚 answeredAsk：上一轮回过的问卷要保持「你回了」，否则历史里的选项会重新变可点
      ctl.close = agentStream(
        runId,
        (event) => {
          if (ctl.settled) return;
          events.push(event);
          scheduleFlush();
          if (event.kind === "action") applyUi(event, key);
          if (event.kind === "done") settle(event, false, events.slice(), key);
          else if (event.kind === "cancelled") settle(event, true, events.slice(), key);
        },
        (msg) => {
          if (ctl.settled) return;
          ctl.settled = true;
          if (ctl.flush) window.cancelAnimationFrame(ctl.flush);
          ctl.close = null;
          clearStopTimer(key);
          if (ctl.cancelled) {
            // 叫停时后端本来就会关流：这是预期，不该报「事件流断了」
            ctl.cancelled = false;
            patchSession(key, (s) => ({
              ...s,
              live: null,
              busy: false,
              stopping: false,
              turns: [...s.turns, { role: "ai", text: "停下了。", stopped: true }],
            }));
            streamsRef.current.delete(key);
            return;
          }
          patchSession(key, (s) => ({
            ...s,
            live: null,
            busy: false,
            stopping: false,
            error: msg,
            turns: [...s.turns, { role: "ai", text: msg + "，稍后再试。" }],
          }));
          streamsRef.current.delete(key);
        },
      );
    },
    [applyUi, clearStopTimer, patchSession, settle],
  );

  const fallback = useCallback(
    async (said: string, exclude: string[], history: unknown, key: string) => {
      try {
        const data = await aiChat(said, { exclude, history });
        patchSession(key, (s) => ({ ...s, turns: [...s.turns, { role: "ai", text: data.reply, data }] }));
      } catch (err) {
        sayTo(key, err instanceof Error ? err.message : "请求失败");
      } finally {
        patchSession(key, (s) => ({ ...s, busy: false }));
      }
    },
    [patchSession, sayTo],
  );

  const ask = useCallback(
    async (message: string, exclude: string[] = []) => {
      const said = message.trim();
      // 发到哪条线程就在入口定死：await 期间用户切走，回复也不能落到别人头上
      const key = activeKeyRef.current;
      const current = sessionsRef.current[key];
      if (!said || current?.busy) return;
      setDraft("");
      setOpen(true);
      clearStopTimer(key);
      patchSession(key, (s) => ({
        ...s,
        busy: true,
        stopping: false,
        error: "",
        turns: [...s.turns, { role: "user", text: said }],
      }));
      const history = (current?.turns ?? []).slice(-4).map((turn) => ({
        role: turn.role === "user" ? "user" : "assistant",
        text: turn.text,
        plan: turn.data?.plan,
      }));
      try {
        const started = await agentStart(said, {
          exclude,
          history,
          thread_id: key,
          context: focus ? { item_id: focus.id, title: focus.title, platform: focus.platform } : undefined,
        });
        listen(started.run_id, key);
      } catch (err) {
        // 后端关掉 Agent 或旧版本没有这条路由：退回一次出计划的老路径
        if (err instanceof ApiError && (err.code === "agent_unavailable" || err.code === "http_error")) {
          await fallback(said, exclude, history, key);
          return;
        }
        sayTo(key, err instanceof Error ? err.message : "请求失败");
        patchSession(key, (s) => ({ ...s, busy: false }));
      }
    },
    [clearStopTimer, fallback, focus, listen, patchSession, sayTo],
  );

  const confirm = useCallback(
    async (confirmId: string, allow: boolean) => {
      const current = sessionsRef.current[activeKeyRef.current];
      if (!current?.live) return;
      setAnswered((prev) => ({ ...prev, [confirmId]: allow }));
      try {
        await agentConfirm(current.live.run_id, confirmId, allow);
      } catch {
        /* 过期了就按后端拒绝处理，不打扰用户 */
      }
    },
    [setAnswered],
  );

  /** 回 Agent 的提问：选选项、或直接说一句，都走这一条路 */
  const answer = useCallback(
    async (askId: string, selected: string[], text: string) => {
      const key = activeKeyRef.current;
      const current = sessionsRef.current[key];
      if (!current?.live) return;
      const show = selected.length ? selected : text ? [text] : [];
      setAnsweredAsk((prev) => ({ ...prev, [askId]: show }));
      try {
        await agentAnswer(current.live.run_id, askId, selected, text);
        inputRef.current?.focus();
      } catch {
        sayTo(key, "这条提问已经收尾了，我把这轮留给你，重新说一句就行。");
      }
    },
    [sayTo, setAnsweredAsk],
  );

  const applySave = useCallback(async (id: string, on: boolean) => {
    savedStore.set(id, on);
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
      savedStore.set(id, !on);
      setSaved((prev) => {
        const next = new Set(prev);
        if (on) next.delete(id);
        else next.add(id);
        return next;
      });
      window.dispatchEvent(new CustomEvent("onefeed:toast", { detail: { text: "没存上，稍后再试。" } }));
    }
  }, []);

  const toggleSave = useCallback(
    (id: string) => {
      const on = !savedStore.get(id);
      void applySave(id, on);
      // 星标只有 16px 的图标变色，点错了根本看不出来 —— 给一句提示加一个当场撤销
      window.dispatchEvent(
        new CustomEvent("onefeed:toast", {
          detail: {
            text: on ? "已加入稍后再看" : "已移出稍后再看",
            action: { label: "撤销", run: () => void applySave(id, !on) },
          },
        }),
      );
    },
    [applySave],
  );

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
      // 内存里已经有这条（哪怕正在后台跑）：只切过去，不重拉、不覆盖
      if (sessionsRef.current[thread.id]) {
        setThread(thread.id);
        setHistoryOpen(false);
        setOpen(true);
        return;
      }
      const token = ++resumeToken.current;
      try {
        const data = await getThread(thread.id);
        // 拉历史期间用户可能又点了另一条，别把旧结果按到他头上
        if (token !== resumeToken.current) return;
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
        patchSession(thread.id, (s) => ({ ...s, turns: next }));
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
    [patchSession, say, setThread],
  );

  const newThread = useCallback(() => {
    // 客户端先铸 id：新会话第一轮就有归属，切走再切回来不会跟「还没拿到 id」打架
    const id = mintThreadId();
    patchSession(id, () => blankSession(id));
    setThread(id);
    setHistoryOpen(false);
    setOpen(true);
    inputRef.current?.focus();
  }, [patchSession, setThread]);

  const stop = useCallback(async () => {
    const key = activeKeyRef.current;
    const current = sessionsRef.current[key];
    if (!current?.live || current.stopping) return;
    const ctl = streamsRef.current.get(key);
    if (ctl) ctl.cancelled = true;
    patchSession(key, (s) => ({ ...s, stopping: true }));
    // 兜底：后端线程可能正卡在一次模型请求里，SSE 迟迟不关时不至于让按钮一直转。
    // 这里只收 UI，不假装采集也跟着停了 —— 采集由后端 cancel 一并叫停，结果走同一份 progress。
    clearStopTimer(key);
    const timer = window.setTimeout(() => {
      if (ctl) {
        ctl.settled = true;
        ctl.close?.();
        ctl.close = null;
      }
      patchSession(key, (s) => ({
        ...s,
        live: null,
        busy: false,
        stopping: false,
        turns: [...s.turns, { role: "ai", text: "停下了。", stopped: true }],
      }));
      streamsRef.current.delete(key);
    }, 8000);
    if (ctl) ctl.timer = timer;
    try {
      const res = await agentCancel(current.live.run_id);
      if (!res.ok) {
        // 停止位没置上 = 这轮早结束了
        clearStopTimer(key);
        if (ctl) ctl.cancelled = false;
        patchSession(key, (s) => ({
          ...s,
          stopping: false,
          busy: false,
          live: null,
          turns: [...s.turns, { role: "ai", text: "这轮已经结束了。" }],
        }));
      }
    } catch {
      clearStopTimer(key);
      if (ctl) ctl.cancelled = false;
      patchSession(key, (s) => ({ ...s, stopping: false }));
      sayTo(key, "没能叫停，稍后再试。");
    }
  }, [clearStopTimer, patchSession, sayTo]);

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
    // 详情页：右栏是常驻槽位的一部分（窄屏才是抽屉），收起只是把 tab 还给栏位，
    // 不做缩回唤起器的转场 —— 那里没有唤起器可缩。右栏/抽屉各自负责退场。
    if (onItemPage) {
      setOpen(false);
      return;
    }
    // 收起方向：抽屉缩回唤起器。唤起器是收起之后才挂上的，新快照里没有它，
    // 所以代位盒子要挂在 apply 里 —— 那样它只进新快照，正好当终点。
    // 到这里的只可能是「抽屉」形态：详情页右栏在上面的分支已经 return 了
    const ghost = createGhost({ agent: "pill" });
    runNav(
      "back",
      () => {
        ghost.mount();
        setOpen(false);
      },
      { after: () => ghost.remove() },
    );
  }, [open, onItemPage]);

  const openWith = useCallback(
    (prefill?: string) => {
      if (typeof prefill === "string") setDraft(prefill);
      if (open) {
        window.setTimeout(() => inputRef.current?.focus(), 30);
        return;
      }
      // 详情页：右栏从右缘长出来（Shell 的宽度补间 / 抽屉滑入），不该拿主页底栏的
      // 胶囊当起点 —— 那会演成「底栏滑到右边」。这里直接开，转场交给栏位自己。
      if (onItemPage) {
        setOpen(true);
        window.setTimeout(() => inputRef.current?.focus(), 30);
        return;
      }
      // 打开方向：唤起器还在旧快照里但没有名字，给它挂个代位盒子，抽屉就从它的位置长出来。
      const ghost = createGhost({ agent: "pill" });
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
    [open, onItemPage],
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

  /* 卸载时别把 SSE 和停止兜底定时器留在后台（每线程各一条） */
  useEffect(
    () => () => {
      for (const ctl of streamsRef.current.values()) {
        ctl.close?.();
        if (ctl.timer != null) window.clearTimeout(ctl.timer);
      }
      streamsRef.current.clear();
    },
    [],
  );

  const mode: AgentSurfaceState["mode"] = !open
    ? "closed"
    : onItemPage && wide
      ? "rail"
      : "sheet";

  const current = sessions[threadId] ?? blankSession(threadId);
  const session = useMemo<AgentSessionState>(
    () => ({
      turns: current.turns,
      busy: current.busy,
      live: current.live,
      answered: current.answered,
      answeredAsk: current.answeredAsk,
      stopping: current.stopping,
      threadId,
      saved,
      error: current.error,
    }),
    [current, threadId, saved],
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
    () => ({
      open: historyOpen,
      items: historyItems,
      loading: historyLoading,
      running: Object.keys(sessions).filter((key) => sessions[key]?.busy),
    }),
    [historyOpen, historyItems, historyLoading, sessions],
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
