import { useCallback, useEffect, useRef, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import TopBar from "./components/TopBar";
import ShortcutHelp from "./components/ShortcutHelp";
import { ConfirmHost } from "./components/ui/Confirm";
import { pushScope, popScope, useHotkeys } from "./motion/useHotkeys";
import FeedPage from "./pages/FeedPage";
import ItemPage from "./pages/ItemPage";
import MarketPage from "./pages/MarketPage";
import SettingsPage from "./pages/SettingsPage";
import NotFound from "./pages/NotFound";
import { getJSON, postJSON, type Health, type RunState, type SettingsResponse, type Summary } from "./api";
import { DUR, EASE, pageVariants } from "./motion";

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

export default function App() {
  const [progress, setProgress] = useState<RunState | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [toast, setToast] = useState("");
  const [help, setHelp] = useState(false);
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
        setProgress(data.state);
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
  // 不用 ⌘/Ctrl+K —— 那是浏览器地址栏/搜索栏的保留键，页面根本收不到（用户实测按了是 Chrome 在响应）。
  useHotkeys("global", {
    "/": () => window.dispatchEvent(new CustomEvent("onefeed:ask")),
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
    <div className="min-h-screen bg-paper">
      {/* 键盘用户第一个 Tab 就能跳过顶栏直达内容 */}
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-3 focus:z-50 focus:rounded-full focus:bg-solid focus:px-4 focus:py-2 focus:text-[13px] focus:text-solid-fg"
      >
        跳到内容
      </a>
      <TopBar health={health} progress={progress} onRefresh={refresh} />
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1180px] px-6 outline-none">
        {/* 走 View Transition 时新页已经以最终样子进了快照，这里不能再播进场动画 */}
        <motion.div
          key={location.pathname}
          className="page-shell"
          initial={instant || reduce ? false : page.initial}
          animate={page.animate}
          transition={{ duration: instant || reduce ? 0 : DUR.page, ease: EASE }}
        >
          <Routes location={location}>
            <Route path="/" element={<FeedPage ctx={ctx} />} />
            <Route path="/item/:id" element={<ItemPage />} />
            <Route path="/market" element={<MarketPage ctx={ctx} />} />
            <Route path="/settings" element={<SettingsPage ctx={ctx} />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </motion.div>
      </main>
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
    </div>
  );
}
