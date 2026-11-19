import { ArrowUp, History, Loader2, Sparkles, Square, Star, Wand2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import type { AgentEvent, AgentThread, AiResponse, FeedItem } from "../api";
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
} from "../api";
import { platform } from "../platform";
import { popScope, pushScope, useHotkeys } from "../motion/useHotkeys";
import { DUR, EASE, SPRING_SOFT } from "../motion/tokens";
import AgentConsole from "./AgentConsole";
import FilterBox from "./FilterBox";

interface Turn {
  role: "user" | "ai";
  text: string;
  data?: AiResponse;
  /** Agent 这轮留下的轨迹（回放同一份） */
  trace?: AgentEvent[];
  /** 这轮是用户叫停的：文案与「正常答完」区分开 */
  stopped?: boolean;
}

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

const HINTS = [
  "今天 B 站有什么 AI 的",
  "随便来点，别老是同一个平台",
  "这周小红书在聊什么",
];

/** 底部悬浮的 AI 入口：一句话找内容，也是"刷一刷"的入口。 */
export default function AiDock({ onOpenItem }: { onOpenItem: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState(false);
  const [live, setLive] = useState<{ run_id: string; events: AgentEvent[] } | null>(null);
  const [answered, setAnswered] = useState<Record<string, boolean>>({});
  const [stopping, setStopping] = useState(false);
  const [focused, setFocused] = useState(false);
  const [hintIndex, setHintIndex] = useState(0);
  /** 回过的提问：ask_id → 选了什么。Agent 停下等答复时要立刻能看到它。 */
  const [answeredAsk, setAnsweredAsk] = useState<Record<string, string[]>>({});
  const setThread = (id: string) => {
    setThreadId(id);
    try {
      if (id) localStorage.setItem("onefeed.agent.thread", id);
      else localStorage.removeItem("onefeed.agent.thread");
    } catch {
      /* 隐私模式下存不了就算了，退化成刷新即新对话 */
    }
  };

  /** 这一轮挂在哪条会话上：接着上一段聊，模型才知道「再来几条」是接着哪儿 */
  const [threadId, setThreadId] = useState(() => {
    // 刷新页面别把「正在聊的这段」丢掉：同一个 thread 才能接着说
    try {
      return localStorage.getItem("onefeed.agent.thread") ?? "";
    } catch {
      return "";
    }
  });
  /** 结果卡片上的星标（本地乐观更新，后端是 item_marks） */
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const [history, setHistory] = useState<{ open: boolean; items: AgentThread[]; loading: boolean }>({
    open: false,
    items: [],
    loading: false,
  });
  const streamRef = useRef<null | (() => void)>(null);
  const settledRef = useRef(false);
  const cancelledRef = useRef(false);
  const stopTimerRef = useRef<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const dockRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  const clearStopTimer = () => {
    if (stopTimerRef.current) {
      window.clearTimeout(stopTimerRef.current);
      stopTimerRef.current = null;
    }
  };

  /** 关面板：焦点若在面板里就还给输入框，否则键盘用户会掉到 body 上 */
  const close = () => {
    if (panelRef.current?.contains(document.activeElement)) inputRef.current?.focus();
    setOpen(false);
  };

  useEffect(
    () => () => {
      streamRef.current?.();
      clearStopTimer();
    },
    [],
  );

  useEffect(() => {
    if (!open) return;
    pushScope("dialog");
    return () => popScope("dialog");
  }, [open]);

  useHotkeys("dialog", { escape: () => close() }, open);

  // 桌面端没有遮罩，点面板外要能关；用 pointerdown 而不是 click，避免拖选文字时误关
  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      const root = dockRef.current;
      if (!root) return;
      if (!root.contains(e.target as Node)) close();
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  // 占位文案每 4s 换一条：静态 placeholder 教不会用户该怎么问
  useEffect(() => {
    if (focused || text) return;
    const timer = window.setInterval(() => setHintIndex((i) => (i + 1) % HINTS.length), 4000);
    return () => window.clearInterval(timer);
  }, [focused, text]);

  // 全局 "/" 与 ⌘/Ctrl+Shift+K 由 App 派发，这里只负责展开并聚焦
  useEffect(() => {
    const onAsk = () => {
      setOpen(true);
      inputRef.current?.focus();
    };
    window.addEventListener("onefeed:ask", onAsk);
    return () => window.removeEventListener("onefeed:ask", onAsk);
  }, []);

  // Tab 只在这一组（面板 + 输入框）里循环：不放行的话焦点会跑到浏览器 UI 上
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || e.altKey || e.ctrlKey || e.metaKey) return;
      const root = dockRef.current;
      if (!root) return;
      const nodes = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (n) => n.offsetParent !== null || n === document.activeElement,
      );
      if (!nodes.length) return;
      const first = nodes[0];
      const lastNode = nodes[nodes.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (!root.contains(active)) {
        e.preventDefault();
        first.focus();
      } else if (!e.shiftKey && active === lastNode) {
        e.preventDefault();
        first.focus();
      } else if (e.shiftKey && active === first) {
        e.preventDefault();
        lastNode.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [turns, busy]);

  const say = (text: string) => setTurns((prev) => [...prev, { role: "ai", text }]);

  const applyUi = (event: AgentEvent) => {
    const payload = (event.data?.payload ?? {}) as Record<string, unknown>;
    if (event.name === "ui_filter") {
      window.dispatchEvent(
        new CustomEvent("onefeed:filter", {
          detail: {
            platforms: Array.isArray(payload.platforms) ? payload.platforms : [],
            keyword: typeof payload.keyword === "string" ? payload.keyword : "",
            range: payload.since === "today" ? "today" : "all",
            sort: typeof payload.sort === "string" ? payload.sort : undefined,
          },
        }),
      );
    } else if (event.name === "ui_open_item" && payload.id) {
      onOpenItem(String(payload.id));
    }
  };

  /** 收尾：done 与 cancelled 共用一份 payload 组装，只差一句文案与标记 */
  const settle = (event: AgentEvent, stopped: boolean, trace: AgentEvent[]) => {
    settledRef.current = true;
    streamRef.current?.();
    streamRef.current = null;
    clearStopTimer();
    const d = (event.data ?? {}) as Record<string, any>;
    const items: FeedItem[] = Array.isArray(d.items) ? d.items : [];
    const data: AiResponse = {
      engine: "agent",
      provider: typeof d.provider === "string" ? d.provider : "",
      plan:
        (d.plan as AiResponse["plan"]) ?? {
          mode: "agent",
          platforms: [],
          kinds: [],
          since: null,
          keyword: "",
          sort: "freshness",
        },
      reply: String(d.reply ?? ""),
      items,
      count: items.length,
      suggestions: Array.isArray(d.suggestions) ? d.suggestions : [],
      understood: String(d.understood ?? ""),
      steps: Number(d.usage?.steps ?? 0),
      ms: Number(d.usage?.ms ?? 0),
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
    setLive(null);
    setBusy(false);
    setStopping(false);
    cancelledRef.current = false;
  };

  const listen = (runId: string) => {
    const events: AgentEvent[] = [];
    settledRef.current = false;
    cancelledRef.current = false;
    setAnswered({});
    // 不回滚 answeredAsk：一轮新对话开始时，上一轮问过的卡片要保持「你回了」
    // 的收束状态，否则历史里的选项会重新变成可点的。
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
        say(`${msg}，稍后再试。`);
      },
    );
  };

  const fallback = async (said: string, exclude: string[], history: unknown) => {
    try {
      const data = await aiChat(said, { exclude, history });
      setTurns((prev) => [...prev, { role: "ai", text: data.reply, data }]);
    } catch (err) {
      say(err instanceof Error ? err.message : "请求失败");
    } finally {
      setBusy(false);
    }
  };

  const ask = async (message: string, exclude: string[] = []) => {
    const said = message.trim();
    if (!said || busy) return;
    setText("");
    setOpen(true);
    clearStopTimer();
    cancelledRef.current = false;
    setStopping(false);
    setBusy(true);
    setTurns((prev) => [...prev, { role: "user", text: said }]);
    const history = turns.slice(-4).map((t) => ({
      role: t.role === "user" ? "user" : "assistant",
      text: t.text,
      plan: t.data?.plan,
    }));
    try {
      const started = await agentStart(said, { exclude, history, thread_id: threadId || undefined });
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
  };

  const confirm = async (confirmId: string, allow: boolean) => {
    if (!live) return;
    const runId = live.run_id;
    setAnswered((prev) => ({ ...prev, [confirmId]: allow }));
    try {
      await agentConfirm(runId, confirmId, allow);
    } catch {
      /* 过期了就按后端拒绝处理，不打扰用户 */
    }
  };

  /** 回 Agent 的提问：选选项、或直接说一句，都走这一条路 */
  const answer = async (askId: string, selected: string[], text: string) => {
    if (!live) return;
    const show = selected.length ? selected : text ? [text] : [];
    setAnsweredAsk((prev) => ({ ...prev, [askId]: show }));
    try {
      await agentAnswer(live.run_id, askId, selected, text);
      inputRef.current?.focus();
    } catch {
      say("这条提问已经收尾了，我把这轮留给你，重新说一句就行。");
    }
  };

  const toggleSave = async (id: string) => {
    const on = !saved.has(id);
    setSaved((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
    try {
      await agentSave(id, on);
    } catch {
      setSaved((prev) => {
        const next = new Set(prev);
        if (on) next.delete(id);
        else next.add(id);
        return next;
      });
    }
  };

  const toggleHistory = async () => {
    const next = !history.open;
    setHistory((h) => ({ ...h, open: next }));
    if (!next) return;
    setHistory((h) => ({ ...h, loading: true }));
    try {
      const data = await listThreads(6);
      setHistory({ open: true, items: data.threads ?? [], loading: false });
    } catch {
      setHistory({ open: true, items: [], loading: false });
    }
  };

  /** 接着上一段聊：把历史问答铺回面板，再发消息就落进同一条线程 */
  const resumeThread = async (thread: AgentThread) => {
    try {
      const data = await getThread(thread.id);
      const next: Turn[] = [];
      for (const run of data.runs ?? []) {
        if (run.input) next.push({ role: "user", text: run.input });
        if (run.reply) next.push({ role: "ai", text: run.reply });
      }
      setTurns(next);
      setThread(thread.id);
      setHistory((h) => ({ ...h, open: false }));
      setOpen(true);
    } catch {
      say("这段对话没读到，稍后再试。");
    }
  };

  const stop = async () => {
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
  };

  const last = [...turns].reverse().find((t) => t.role === "ai" && t.data)?.data;

  const applyFilter = (data: AiResponse) => {
    // plan.since 是检索时真实生效的起始秒；只有落在 36 小时内的才算「今天」
    const since = Number(data.plan.since || 0);
    const detail = {
      platforms: data.plan.platforms,
      keyword: data.plan.keyword,
      range: since && Date.now() / 1000 - since <= 36 * 3600 ? "today" : "all",
      sort: data.plan.sort,
    };
    window.dispatchEvent(new CustomEvent("onefeed:filter", { detail }));
    setOpen(false);
  };

  return (
    <>
      <AnimatePresence>
        {open ? (
          <motion.div
            key="scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduce ? 0 : 0.18 }}
            className="fixed inset-0 z-30 bg-solid/10 md:hidden"
            onClick={close}
            aria-hidden
          />
        ) : null}
      </AnimatePresence>

      {/* 挂到 body：切页动画会给页面容器加 transform，fixed 元素留在里面会跟着跑 */}
      {createPortal(
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center px-4 pb-4">
        {/* DOM 顺序：面板在前、输入框在后（面板在视觉上方）。Tab 用下面的焦点陷阱在两者之间循环 */}
        <div ref={dockRef} className="pointer-events-auto flex w-full max-w-[760px] flex-col gap-3">
          {/* 不用 AnimatePresence：退出动画在动画帧被节流的环境（隐藏标签页 / reduce）里可能永远不结束，
              面板会卡在 DOM 里关不掉。关闭要即时，入场动画保留。 */}
          {open ? (
            <motion.div
              key="panel"
              ref={panelRef}
              role="dialog"
              aria-modal="true"
              aria-label="找内容"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={reduce ? { duration: 0 } : { type: "tween", duration: DUR.base, ease: EASE }}
              className="flex max-h-[62vh] flex-col overflow-hidden rounded-card border border-line bg-paper shadow-[0_18px_50px_rgba(20,20,20,0.14)]"
            >
              <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
                <Sparkles size={14} className="text-ink" />
                <span className="text-[13px] font-medium">找内容</span>
                <button
                  onClick={() => void toggleHistory()}
                  aria-expanded={history.open}
                  className="ml-auto rounded p-1 text-fade transition hover:bg-wash hover:text-ink"
                  aria-label="最近的对话"
                  title="最近的对话"
                >
                  <History size={15} />
                </button>
                <button
                  onClick={close}
                    className="rounded p-1 text-fade transition hover:bg-wash hover:text-ink"
                  aria-label="收起"
                  title="收起（Esc）"
                >
                  <X size={15} />
                </button>
              </div>

              <div
                ref={listRef}
                aria-live="polite"
                aria-relevant="additions text"
                className="min-h-[180px] flex-1 space-y-4 overflow-y-auto px-4 py-4"
              >
                {history.open ? (
                  <div className="space-y-1.5 border-b border-line/60 pb-3">
                    <div className="flex items-center gap-2">
                      <span className="text-[11.5px] text-fade">
                        {history.loading
                          ? "正在翻…"
                          : history.items.length
                            ? "接着上一段聊："
                            : "还没有别的对话。"}
                      </span>
                      <button
                        type="button"
                        onClick={() => {
                          setTurns([]);
                          setThread("");
                          setHistory((h) => ({ ...h, open: false }));
                          inputRef.current?.focus();
                        }}
                        className="ml-auto text-[11px] text-fade underline-offset-2 transition hover:text-ink hover:underline"
                      >
                        开一段新的
                      </button>
                    </div>
                    {history.items.map((item) => (
                      <button
                        key={item.id}
                        onClick={() => void resumeThread(item)}
                        className="flex w-full items-center gap-2 rounded-lg border border-line/70 px-2.5 py-1.5 text-left transition hover:border-ink/20 hover:bg-wash/40"
                      >
                        <span className="min-w-0 flex-1 truncate text-[12.5px]">
                          {item.title || "新对话"}
                        </span>
                        <span className="shrink-0 text-[11px] text-fade">{item.runs} 轮</span>
                      </button>
                    ))}
                  </div>
                ) : null}

                {turns.length === 0 ? (
                  <div className="space-y-2">
                    <p className="text-[13px] text-muted">你可以直接说要什么，平台、时间、类型都算数。</p>
                    <div className="flex flex-wrap gap-2">
                      {HINTS.map((hint) => (
                        <button
                          key={hint}
                          onClick={() => void ask(hint)}
                          className="rounded-full border border-line px-3 py-1.5 text-[12px] text-muted transition hover:border-ink/25 hover:text-ink"
                        >
                          {hint}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}

                {turns.map((turn, index) =>
                  turn.role === "user" ? (
                    <div key={index} className="rise flex justify-end">
                      <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-solid px-3.5 py-2 text-[13px] text-solid-fg">
                        {turn.text}
                      </div>
                    </div>
                  ) : (
                    <div key={index} className="rise space-y-2.5">
                      <div className="flex items-start gap-2">
                        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line">
                          <Sparkles size={12} />
                        </span>
                        <div className="min-w-0">
                          <p className="text-[13px] leading-relaxed">{turn.text}</p>
                          {turn.stopped ? (
                            <span className="mt-1 inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[11px] text-fade">
                              <Square size={8} fill="currentColor" />
                              按你点的停止收的尾
                            </span>
                          ) : null}
                          {turn.data ? (
                            <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-fade">
                              <span className="rounded-full border border-line px-2 py-0.5">{turn.data.understood}</span>
                              <span>{turn.data.count} 条</span>
                              {turn.data.engine === "agent" && turn.data.steps ? (
                                <span className="text-fade/80">
                                  自己查了 {turn.data.steps} 次
                                  {turn.data.ms ? ` · ${(turn.data.ms / 1000).toFixed(1)}s` : ""}
                                </span>
                              ) : null}
                            </div>
                          ) : null}
                        </div>
                      </div>

                      {turn.trace?.length ? (
                        <div className="pl-8">
                          <AgentConsole
                            events={turn.trace}
                            answered={answered}
                            answeredAsk={answeredAsk}
                          />
                        </div>
                      ) : null}

                      {turn.data?.items.length ? (
                        <div className="space-y-1.5 pl-8">
                          {turn.data.items.slice(0, 8).map((item) => (
                            <MiniRow
                              key={item.id}
                              item={item}
                              saved={saved.has(item.id)}
                              onToggleSave={() => void toggleSave(item.id)}
                              onOpen={() => onOpenItem(item.id)}
                            />
                          ))}
                        </div>
                      ) : null}

                      {turn.data ? (
                        <div className="flex flex-wrap items-center gap-2 pl-8">
                          <button
                            onClick={() => applyFilter(turn.data as AiResponse)}
                            className="rounded-full bg-solid px-3 py-1.5 text-[12px] text-solid-fg"
                          >
                            用这个条件刷
                          </button>
                          <button
                            onClick={() => void ask("再换一批", (turn.data as AiResponse).items.map((i) => i.id))}
                            className="rounded-full border border-line px-3 py-1.5 text-[12px] text-muted transition hover:border-ink/25 hover:text-ink"
                          >
                            换一批
                          </button>
                          {turn.data.suggestions.slice(0, 2).map((s) => (
                            <button
                              key={s}
                              onClick={() => void ask(s)}
                              className="rounded-full border border-line px-3 py-1.5 text-[12px] text-muted transition hover:border-ink/25 hover:text-ink"
                            >
                              {s}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </div>
                  ),
                )}

                {live ? (
                  <div className="rise space-y-1.5">
                    <AgentConsole
                      events={live.events}
                      running
                      answered={answered}
                      onConfirm={confirm}
                      answeredAsk={answeredAsk}
                      onAnswer={(askId, selected, free) => void answer(askId, selected, free)}
                    />
                    <div className="flex items-center gap-2 pl-1">
                      <button
                        onClick={() => void stop()}
                        disabled={stopping}
                        aria-label={stopping ? "正在停止" : "停止这一轮"}
                        className="flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[11px] text-fade transition hover:border-ink/25 hover:text-ink disabled:opacity-60"
                      >
                        {stopping ? (
                          <Loader2 size={11} className="animate-spin" />
                        ) : (
                          <Square size={9} fill="currentColor" />
                        )}
                        {stopping ? "正在停止" : "停止"}
                      </button>
                    </div>
                  </div>
                ) : null}

                {busy && !live ? (
                  <div className="flex items-center gap-2 text-[12px] text-fade">
                    <Loader2 size={14} className="animate-spin" />
                    Agent 正在本地库里翻…
                  </div>
                ) : null}
              </div>

              <div className="border-t border-line px-4 py-2.5">
                <button
                  onClick={() => setManual((v) => !v)}
                  className="text-[12px] text-fade transition hover:text-ink"
                >
                  {manual ? "收起手动筛选" : "手动筛选"}
                </button>
                <AnimatePresence initial={false}>
                  {manual ? (
                    <motion.div
                      key="manual"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: reduce ? 0 : 0.22, ease: [0.22, 1, 0.36, 1] }}
                      style={{ overflow: "hidden" }}
                    >
                      <FilterBox
                        value=""
                        parsed={null}
                        onSubmit={(q) => {
                          window.dispatchEvent(new CustomEvent("onefeed:filter", { detail: { keyword: q } }));
                          setOpen(false);
                        }}
                      />
                    </motion.div>
                  ) : null}
                </AnimatePresence>
              </div>
            </motion.div>
          ) : null}

          <motion.form
            onSubmit={(e) => {
              e.preventDefault();
              void ask(text);
            }}
            animate={reduce ? undefined : { scale: focused ? 1.012 : 1, y: focused ? -1 : 0 }}
            transition={SPRING_SOFT}
            className={`flex h-12 items-center gap-2 border bg-paper/95 px-3 backdrop-blur transition-[border-color,box-shadow,border-radius] duration-200 ${open ? "rounded-[22px]" : "rounded-full"} ${
              focused
                ? "border-ink/35 shadow-[0_12px_34px_rgba(20,20,20,0.16)]"
                : "border-line shadow-[0_10px_30px_rgba(20,20,20,0.12)]"
            }`}
          >
            <motion.span
              animate={reduce ? undefined : { rotate: focused ? -10 : 0, scale: focused ? 1.06 : 1 }}
              transition={SPRING_SOFT}
              className="flex h-7 w-7 items-center justify-center rounded-full bg-solid text-solid-fg"
            >
              <Wand2 size={14} />
            </motion.span>
            <input
              ref={inputRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onFocus={() => setFocused(true)}
              onClick={() => setOpen(true)}
              onKeyDown={(e) => {
                if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
                  e.preventDefault();
                  setOpen(true);
                }
              }}
              onBlur={() => setFocused(false)}
              aria-label="向 OneFeed 提问"
              placeholder={"问 OneFeed：" + HINTS[hintIndex]}
              className="h-full flex-1 bg-transparent text-[13px] outline-none placeholder:text-fade"
            />
            {last ? (
              <button
                type="button"
                onClick={() => void ask("随便来点", last.items.map((i) => i.id))}
                className="hidden shrink-0 rounded-full border border-line px-2.5 py-1 text-[12px] text-muted transition hover:border-ink/25 hover:text-ink md:block"
              >
                刷一刷
              </button>
            ) : null}
            {/* 同一个位置：不忙时是「发送」，忙时变「停止」——不用去面板里找那颗按钮 */}
            {busy ? (
              <motion.button
                key="stop"
                type="button"
                onClick={() => void stop()}
                disabled={stopping}
                whileTap={stopping ? undefined : { scale: 0.9 }}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-solid text-solid-fg transition disabled:opacity-60"
                aria-label={stopping ? "正在停止" : "停止这一轮"}
                title={stopping ? "正在停止…" : "停止这一轮"}
              >
                {stopping ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <motion.span
                    key="square"
                    initial={reduce ? undefined : { scale: 0.6, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{ duration: reduce ? 0 : 0.14 }}
                    className="flex"
                  >
                    <Square size={11} fill="currentColor" />
                  </motion.span>
                )}
              </motion.button>
            ) : (
              <motion.button
                key="send"
                type="submit"
                disabled={!text.trim()}
                whileTap={text.trim() ? { scale: 0.9 } : undefined}
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-solid text-solid-fg transition disabled:opacity-30"
                aria-label="发送"
              >
                <motion.span
                  initial={reduce ? undefined : { y: 6, opacity: 0 }}
                  animate={{ y: 0, opacity: 1 }}
                  transition={{ duration: reduce ? 0 : 0.16 }}
                  className="flex"
                >
                  <ArrowUp size={15} />
                </motion.span>
              </motion.button>
            )}
          </motion.form>
        </div>
      </div>,
      document.body,
      )}
    </>
  );
}

function MiniRow({
  item,
  saved,
  onOpen,
  onToggleSave,
}: {
  item: FeedItem;
  saved: boolean;
  onOpen: () => void;
  onToggleSave: () => void;
}) {
  const p = platform(item.platform);
  return (
    <div className="flex w-full items-start gap-1 rounded-lg border border-line/70 transition hover:border-ink/20 hover:bg-wash/40">
      <button
        onClick={onOpen}
        className="flex min-w-0 flex-1 items-start gap-2.5 px-2 py-1.5 text-left"
      >
      {item.cover ? (
        <img src={item.cover} alt="" loading="lazy" referrerPolicy="no-referrer"
          className="h-12 w-16 shrink-0 rounded object-cover" />
      ) : (
        <span className="flex h-12 w-16 shrink-0 items-center justify-center rounded bg-wash text-[10px] text-fade">
          {p.label}
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 text-[12.5px] leading-snug">{item.title}</span>
        <span className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] text-fade">
          <span className="text-muted">{p.label}</span>
          {(item.reasons || []).slice(0, 2).map((r) => (
            <span key={r}>{r}</span>
          ))}
        </span>
      </span>
      </button>
      <button
        type="button"
        onClick={onToggleSave}
        aria-pressed={saved}
        aria-label={saved ? "取消收藏" : "收藏这条"}
        title={saved ? "取消收藏" : "收藏"}
        className={`mr-1 mt-1.5 shrink-0 rounded p-1 transition hover:bg-wash ${
          saved ? "text-ink" : "text-fade hover:text-ink"
        }`}
      >
        <Star size={13} fill={saved ? "currentColor" : "none"} />
      </button>
    </div>
  );
}
