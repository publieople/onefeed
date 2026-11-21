import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import ShortcutHelp from "./components/ShortcutHelp";
import Shell from "./layout/Shell";
import { RailSlotProvider } from "./layout/RailSlot";
import { ConfirmHost } from "./components/ui/Confirm";
import { useHotkeys } from "./motion/useHotkeys";
import FeedPage from "./pages/FeedPage";
import { loadItemPageComponent } from "./pages/itemPageLoader";
// 详情页曾经必须在主包里：共享元素转场要在点击后立刻拿到新快照，异步 chunk 会在转场里
// 插一段空白。现在拆成独立 chunk，但这个前提用另一条路保住——卡片悬停/按下就预热模块，
// 冷点进来先 await 模块就位再起转场（见 pages/itemPageLoader.ts）。主包因此少了整个详情页。
const ItemPage = lazy(loadItemPageComponent);

const MarketPage = lazy(() => import("./pages/MarketPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const AgentPage = lazy(() => import("./pages/AgentPage"));
const NotFound = lazy(() => import("./pages/NotFound"));
import { AgentProvider } from "./agent/AgentProvider";
import AgentSurface from "./agent/AgentSurface";
import { getJSON, postJSON, type Health, type RunState, type SettingsResponse, type Summary } from "./api";
import ScrollTop from "./components/ScrollTop";
import { DUR, EASE, pageVariants } from "./motion";
import { useSmoothWheelScroll } from "./motion/useSmoothWheelScroll";

/** 一条浮出来的提示；带 action 时右侧多一个按钮（撤销这类） */
interface ToastMsg {
  text: string;
  action?: { label: string; run: () => void };
}

export interface OutletCtx {
  progress: RunState | null;
  reloadKey: number;
  refresh: () => void;
  summary: Summary | null;
  settings: SettingsResponse | null;
  reloadSettings: () => Promise<void>;
  bump: () => void;
}

const IDLE: RunState = {
  running: false,
  started_at: 0,
  finished_at: 0,
  done: 0,
  total: 0,
  error: "",
  plugins: {},
};

/** 进度轮询的相等判断：plugins 明细变了也算变，但普通心跳不算 */
function sameRun(a: RunState | null, b: RunState): boolean {
  if (!a) return false;
  return (
    a.running === b.running &&
    a.done === b.done &&
    a.total === b.total &&
    a.error === b.error &&
    a.started_at === b.started_at &&
    a.finished_at === b.finished_at
  );
}

export default function App() {
  const [progress, setProgress] = useState<RunState | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [toast, setToast] = useState<ToastMsg | null>(null);
  // 所有 toast 共用一个定时器：之前「全局提示」和「开始刷新」各挂各的 setTimeout，
  // 谁先到点谁清空，后一条还没读完就被前一条的定时器抹掉了。
  const toastTimer = useRef<number | null>(null);
  const showToast = useCallback((next: ToastMsg) => {
    setToast(next);
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    // 带「撤销」的要留够时间让人看清并点下去
    toastTimer.current = window.setTimeout(() => setToast(null), next.action ? 5200 : 2400);
  }, []);
  useEffect(() => () => {
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
  }, []);
  // 任何组件都能报一句结果（卡片菜单复制链接、收藏切换），不必把 toast 状态传下去
  useEffect(() => {
    const onToast = (event: Event) => {
      const detail = (event as CustomEvent<{ text?: string; action?: { label: string; run: () => void } }>).detail;
      if (!detail?.text) return;
      showToast({ text: detail.text, action: detail.action });
    };
    window.addEventListener("onefeed:toast", onToast);
    return () => window.removeEventListener("onefeed:toast", onToast);
  }, [showToast]);
  const [help, setHelp] = useState(false);
  // 滚轮缓动：Windows 的 Chrome 一格是整整一段，容器自己的 scroll-behavior 管不到滚轮。
  // 页面本体和带 data-smooth-scroll 的侧栏共用一套引擎（事件当帧走大半、余量滑行），
  // 每帧还有 MAX_SPEED × dt 上限，冲不进还没取回来的地方。
  useSmoothWheelScroll();
  const wasRunning = useRef(false);
  // 演示模式：不联网，刷新只是重放同一份本地样例。轮询里要据实说明，
  // 否则用户会以为「点了刷新但内容没动」是坏了（2026-11-21 就是这么被问的）。
  const demoRef = useRef(false);
  // 轮询里要能触发「仍要抓」，但 refresh 定义在轮询 effect 之后（会在依赖数组里 TDZ），
  // 所以走一遍 ref
  const refreshRef = useRef<(force?: boolean) => void>(() => {});
  const location = useLocation();
  const reduce = useReducedMotion();
  // 走 View Transition 的那一次跳转不播进场动画：新页要立刻以最终样子进快照
  const instant = Boolean((location.state as { vt?: boolean } | null)?.vt);
  // 从首页进详情/市场算「往里走」，回到首页算「往回走」，切页方向跟着走
  const depth = (p: string) => (p === "/" ? 0 : 1);
  const prevPath = useRef(location.pathname);
  const dir: 1 | -1 = depth(location.pathname) >= depth(prevPath.current) ? 1 : -1;
  useEffect(() => {
    prevPath.current = location.pathname;
    // 共享元素变形那次跳转自己决定落点：进详情已经滚到顶，返回要滚回原卡片。
    // 这里再 scrollTo(0) 会把返回的位置冲掉（effect 在绘制后才跑）。
    if ((location.state as { vt?: boolean } | null)?.vt) return;
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [location.pathname, location.state]);
  const page = pageVariants(dir);

  const reloadSettings = useCallback(async () => {
    try {
      setSettings(await getJSON<SettingsResponse>("/api/settings"));
    } catch {
      /* 设置读不到不阻塞信息流 */
    }
  }, []);

  useEffect(() => {
    void reloadSettings();
  }, [reloadSettings]);

  const loadSummary = useCallback(async () => {
    try {
      const [s, h] = await Promise.all([getJSON<Summary>("/api/summary"), getJSON<Health>("/api/health")]);
      setSummary(s);
      setHealth(h);
      demoRef.current = Boolean(h.demo);
    } catch {
      /* 摘要失败不影响主流程 */
    }
  }, []);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const data = await getJSON<{ state: RunState }>("/api/progress");
        if (!alive) return;
        // 1600ms 一次轮询，绝大多数时候什么都没变：只在真变了才 setState，
        // 否则顶栏、进度条、每张卡都会跟着重渲染一轮。
        setProgress((prev) => (sameRun(prev, data.state) ? prev : data.state));
        if (wasRunning.current && !data.state.running && data.state.done > 0) {
          setReloadKey((k) => k + 1);
          void loadSummary();
          // 一轮结束后据实说清楚：加了几条、谁失败、谁在冷却。
          // 之前只闪一句「开始刷新」，内容没变时用户没法判断是没抓到还是坏了。
          const rows = Object.entries(data.state.plugins ?? {});
          const added = rows.reduce(
            (n, [, p]) => n + (p.status === "ok" ? Number(p.count || 0) : 0),
            0,
          );
          const failed = rows.filter(([, p]) => p.status === "failed");
          const cooling = rows.filter(([, p]) => p.status === "skipped");
          if (demoRef.current) {
            showToast({ text: "演示模式：内容来自本地样例，这一轮只是重放，不会有新内容" });
          } else if (!added && !failed.length && cooling.length) {
            const now = Math.floor(Date.now() / 1000);
            const wait = Math.min(
              ...cooling.map(([, p]) => Math.max(1, Number(p.next_at || 0) - now)),
            );
            showToast({
              text: "平台都在冷却中，最早 " + wait + " 秒后才能再抓",
              action: { label: "仍要抓", run: () => refreshRef.current(true) },
            });
          } else {
            const bits = ["刷新完成：新增 " + added + " 条"];
            if (failed.length) bits.push(failed.length + " 个平台失败");
            if (cooling.length) bits.push(cooling.length + " 个平台冷却中");
            showToast({ text: bits.join(" · ") });
          }
        }
        wasRunning.current = data.state.running;
      } catch {
        /* 后端没起来时静默重试 */
      }
    };
    void tick();
    const timer = window.setInterval(tick, 1600);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [loadSummary, showToast]);

  const refresh = useCallback(async (force: boolean = false) => {
    // 按钮把 React 事件当第一个参数传进来时 force 会是个对象；只认严格 true，
    // 否则 JSON.stringify 整个 SyntheticEvent 会当场报 circular structure。
    const bypass = force === true;
    try {
      const res = await postJSON<{ ok: boolean; state?: RunState }>("/api/refresh", { force: bypass });
      const state = res?.state;
      // 全部平台都在冷却时后端不会起线程：这一刻就能说清楚，不必等下一轮轮询。
      if (state && !state.running && state.error && state.error.includes("冷却")) {
        const now = Math.floor(Date.now() / 1000);
        const waits = Object.values(state.plugins ?? {})
          .map((p) => Number(p.next_at || 0) - now)
          .filter((n) => n > 0);
        const wait = waits.length ? Math.min(...waits) : 0;
        showToast({
          text: "平台都在冷却中，最早 " + wait + " 秒后才能再抓",
          action: { label: "仍要抓", run: () => refreshRef.current(true) },
        });
        setProgress(state);
        wasRunning.current = false;
        return;
      }
      showToast({ text: bypass ? "开始抓取（已跳过平台冷却）" : "开始刷新" });
      wasRunning.current = true;
      setProgress(state ?? { ...IDLE, running: true });
    } catch (err) {
      showToast({ text: (err as Error).message });
    }
  }, [showToast]);

  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  const bump = useCallback(() => {
    setReloadKey((k) => k + 1);
    void loadSummary();
    void reloadSettings();
  }, [loadSummary, reloadSettings]);

  // 全局快捷键：「/」叫出 AI 输入框，「?」看键位表，「t」换主题，「r」刷新一轮。
  // ⌘/Ctrl+K 保留：页面收得到，但要靠 useHotkeys 里的 preventDefault 吞掉地址栏默认动作，
  // 否则面板开了、地址栏也聚焦，看起来像「没聚焦」。
  useHotkeys("global", {
    "/": () => window.dispatchEvent(new CustomEvent("onefeed:ask")),
    // Ctrl/⌘+K 是这类产品的惯例，Chrome 允许页面 preventDefault（不吞的话地址栏会一起聚焦）。
    // 不再绑 mod+shift+k：同一个动作挂两个键，键位表里却只写一个，等于给人一个隐形的坑。
    "mod+k": () => window.dispatchEvent(new CustomEvent("onefeed:ask")),
    "?": () => setHelp(true),
    t: () => window.dispatchEvent(new CustomEvent("onefeed:theme")),
    r: () => void refresh(),
  });

  const ctx: OutletCtx = { progress, reloadKey, refresh, summary, settings, reloadSettings, bump };

  return (
    // Agent 的会话挂在路由之上：换页面（包括 Agent 自己打开的那一条）都不重建
    <AgentProvider>
      <RailSlotProvider>
      <Shell health={health} progress={progress} onRefresh={refresh} onHelp={() => setHelp(true)}>
        {/* 走 View Transition 时新页已经以最终样子进了快照，这里不能再播进场动画 */}
        <motion.div
          key={location.pathname}
          className="page-shell"
          initial={instant || reduce ? false : page.initial}
          animate={page.animate}
          transition={{ duration: instant || reduce ? 0 : DUR.page, ease: EASE }}
        >
          <Suspense
            fallback={
              <div className="pt-10">
                <div className="h-6 w-40 animate-pulse rounded bg-wash" />
                <div className="mt-6 h-[220px] animate-pulse rounded-card border border-line bg-paper" />
              </div>
            }
          >
            <Routes location={location}>
              <Route path="/" element={<FeedPage ctx={ctx} />} />
              <Route path="/item/:id" element={<ItemPage />} />
              <Route path="/market" element={<MarketPage ctx={ctx} />} />
              <Route path="/settings" element={<SettingsPage ctx={ctx} />} />
              <Route path="/agent" element={<AgentPage />} />
              <Route path="/agent/:threadId" element={<AgentPage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </motion.div>
      </Shell>
      </RailSlotProvider>
      {/* 三形态的落点：唤起器 / 底部抽屉（右栏槽位在 Shell 里） */}
      <AgentSurface />
      <ScrollTop />
      <AnimatePresence>
        {toast ? (
          <motion.div
            key="toast"
            role="status"
            aria-live="polite"
            initial={{ opacity: 0, y: 12, scale: 0.97, x: "-50%" }}
            animate={{ opacity: 1, y: 0, scale: 1, x: "-50%" }}
            exit={{ opacity: 0, y: 12, scale: 0.97, x: "-50%" }}
            transition={{ duration: reduce ? 0 : DUR.base, ease: EASE }}
            className="fixed bottom-24 left-1/2 z-50 flex items-center gap-3 rounded-full bg-solid py-2.5 pl-5 pr-2.5 text-[13px] text-solid-fg shadow-pop"
          >
            {toast.text}
            {toast.action ? (
              <button
                onClick={() => {
                  const run = toast.action?.run;
                  setToast(null);
                  if (toastTimer.current) window.clearTimeout(toastTimer.current);
                  run?.();
                }}
                className="rounded-full bg-solid-fg/15 px-3 py-1 text-[12px] font-medium text-solid-fg transition hover:bg-solid-fg/25"
              >
                {toast.action.label}
              </button>
            ) : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
      {/* 全站确认框的落点：任何页面 await confirmDialog(...) 都渲染在这里 */}
        <ConfirmHost />
        <ShortcutHelp open={help} onClose={() => setHelp(false)} />
    </AgentProvider>
  );
}