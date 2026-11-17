import { useCallback, useEffect, useRef, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import TopBar from "./components/TopBar";
import FeedPage from "./pages/FeedPage";
import ItemPage from "./pages/ItemPage";
import MarketPage from "./pages/MarketPage";
import SettingsPage from "./pages/SettingsPage";
import { getJSON, postJSON, type Health, type RunState, type SettingsResponse, type Summary } from "./api";

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
  const wasRunning = useRef(false);
  const location = useLocation();
  const reduce = useReducedMotion();

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
      setToast("开始刷新，六路数据正在路上");
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

  const ctx: OutletCtx = { progress, reloadKey, refresh, summary, settings, reloadSettings, bump };

  return (
    <div className="min-h-screen bg-paper">
      <TopBar health={health} progress={progress} onRefresh={refresh} />
      <main className="mx-auto w-full max-w-[1180px] px-6">
        {/* 切页时旧页先淡出再让新页进场，避免两页同时闪一下 */}
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            className="page-shell"
            initial={reduce ? false : { opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduce ? 0 : 0.16, ease: "easeOut" }}
          >
            <Routes location={location}>
              <Route path="/" element={<FeedPage ctx={ctx} />} />
              <Route path="/item/:id" element={<ItemPage />} />
              <Route path="/market" element={<MarketPage ctx={ctx} />} />
              <Route path="/settings" element={<SettingsPage ctx={ctx} />} />
            </Routes>
          </motion.div>
        </AnimatePresence>
      </main>
      <AnimatePresence>
        {toast ? (
          <motion.div
            key="toast"
            initial={{ opacity: 0, y: 12, scale: 0.97, x: "-50%" }}
            animate={{ opacity: 1, y: 0, scale: 1, x: "-50%" }}
            exit={{ opacity: 0, y: 12, scale: 0.97, x: "-50%" }}
            transition={{ duration: reduce ? 0 : 0.22, ease: [0.22, 1, 0.36, 1] }}
            className="fixed bottom-6 left-1/2 z-50 rounded-full bg-ink px-5 py-2.5 text-[13px] text-white shadow-pop"
          >
            {toast}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
