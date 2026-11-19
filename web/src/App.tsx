import { Suspense, lazy, useCallback, useEffect, useRef, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import ShortcutHelp from "./components/ShortcutHelp";
import Shell from "./layout/Shell";
import { RailSlotProvider } from "./layout/RailSlot";
import { ConfirmHost } from "./components/ui/Confirm";
import { pushScope, popScope, useHotkeys } from "./motion/useHotkeys";
import FeedPage from "./pages/FeedPage";
// 详情页必须跟着主包一起到：共享元素转场要在点击后立刻拿到新快照，
// 拆成异步 chunk 会在转场里插一段空白。其余三页不在转场路径上，按需加载。
import ItemPage from "./pages/ItemPage";

const MarketPage = lazy(() => import("./pages/MarketPage"));
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const AgentPage = lazy(() => import("./pages/AgentPage"));
const NotFound = lazy(() => import("./pages/NotFound"));
import { AgentProvider } from "./agent/AgentProvider";
import AgentSurface from "./agent/AgentSurface";
import { getJSON, postJSON, type Health, type RunState, type SettingsResponse, type Summary } from "./api";
import ScrollTop from "./components/ScrollTop";
import { DUR, EASE, pageVariants } from "./motion";
import { useScrollSpeedCap } from "./motion/useScrollSpeedCap";

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
  const [toast, setToast] = useState("");
  const [help, setHelp] = useState(false);
  // 信息流的滚轮限速：翻得太快会冲到还没取回来的地方，这里按每秒像素上限放行
  useScrollSpeedCap();
  const wasRunning = useRef(false);
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
  }, [loadSummary]);

  const refresh = useCallback(async () => {
    try {
      await postJSON("/api/refresh");
      setToast("开始刷新");
      wasRunning.current = true;
      setProgress({ ...IDLE, running: true });
    } catch (err) {
      setToast((err as Error).message);
    }
    window.setTimeout(() => setToast(""), 3200);
  }, []);

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
    // Ctrl/⌘+K 是这类产品的惯例，Chrome 允许页面 preventDefault（不吞的话地址栏会一起聚焦）
    "mod+k": () => window.dispatchEvent(new CustomEvent("onefeed:ask")),
    "mod+shift+k": () => window.dispatchEvent(new CustomEvent("onefeed:ask")),
    "?": () => setHelp(true),
    t: () => window.dispatchEvent(new CustomEvent("onefeed:theme")),
    r: () => void refresh(),
  });

  // 帮助层压在快捷键栈顶上，底下的列表/全局键让位
  useEffect(() => {
    if (!help) return;
    pushScope("dialog");
    return () => popScope("dialog");
  }, [help]);

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
            initial={{ opacity: 0, y: 12, scale: 0.97, x: "-50%" }}
            animate={{ opacity: 1, y: 0, scale: 1, x: "-50%" }}
            exit={{ opacity: 0, y: 12, scale: 0.97, x: "-50%" }}
            transition={{ duration: reduce ? 0 : DUR.base, ease: EASE }}
            className="fixed bottom-24 left-1/2 z-50 rounded-full bg-solid px-5 py-2.5 text-[13px] text-solid-fg shadow-pop"
          >
            {toast}
          </motion.div>
        ) : null}
      </AnimatePresence>
      {/* 全站确认框的落点：任何页面 await confirmDialog(...) 都渲染在这里 */}
        <ConfirmHost />
        <ShortcutHelp open={help} onClose={() => setHelp(false)} />
    </AgentProvider>
  );
}
