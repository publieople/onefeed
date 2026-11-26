import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Copy, ExternalLink, LogIn, LogOut, RefreshCw, RotateCcw, Save } from "lucide-react";
import { useNavigate } from "react-router-dom";
import type { OutletCtx } from "../App";
import {
  agentRuns,
  agentUndo,
  authRows as fetchAuthRows,
  getJSON,
  postJSON,
  putJSON,
  type AgentRunRow,
  type AuthRow,
  type AuthState,
  type Health,
  type LoginStatus,
  type PluginsResponse,
  type SettingsResponse,
  type SettingsValues,
} from "../api";
import { timeAgo } from "../format";
import { PLATFORMS, platform } from "../platform";
import SettingSection from "../components/SettingSection";
import AiProviders from "../components/AiProviders";
import { choiceDialog, confirmDialog } from "../components/ui/Confirm";

/**
 * 数字输入框。直接 `Number(e.target.value)` 的问题是：清空输入框会静默变成 0，
 * 而且 0 低于 min 也不会被拦（表单不在 <form> 里，min/max 只是装饰）。
 * 这里留一份草稿：打字时只在合法区间内写回表单，清空则等失焦时还原上次的值。
 */
function NumberField({
  value,
  min,
  max,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  onChange: (next: number) => void;
}) {
  const [draft, setDraft] = useState(String(value));
  const focused = useRef(false);
  useEffect(() => {
    // 外部把值改了（恢复默认、保存后回填）时同步，但别打断正在打字的人
    if (!focused.current) setDraft(String(value));
  }, [value]);
  const clamp = (raw: string): number | null => {
    const n = Math.round(Number(raw));
    if (!raw.trim() || !Number.isFinite(n)) return null;
    return Math.min(max, Math.max(min, n));
  };
  return (
    <input
      type="number"
      inputMode="numeric"
      min={min}
      max={max}
      value={draft}
      onFocus={() => {
        focused.current = true;
      }}
      onChange={(e) => {
        const raw = e.target.value;
        setDraft(raw);
        const next = clamp(raw);
        if (next !== null) onChange(next);
      }}
      onBlur={(e) => {
        focused.current = false;
        const next = clamp(e.target.value);
        setDraft(String(next ?? value));
        if (next !== null && next !== value) onChange(next);
      }}
      className="mt-1.5 h-9 w-full rounded-lg border border-line bg-paper px-3 text-[13px] outline-none focus:border-ink/40"
    />
  );
}

const SECTIONS = [
  { id: "status", label: "运行状态" },
  { id: "collect", label: "采集与排序" },
  { id: "ai", label: "AI 助手" },
  { id: "agent", label: "Agent 活动" },
  { id: "auth", label: "登录态" },
  { id: "plugins", label: "已装插件" },
];

const STATE_TEXT: Record<string, { label: string; tone: string }> = {
  available: { label: "已登录", tone: "bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-500/30" },
  need_login: { label: "待登录", tone: "bg-amber-50 dark:bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-500/30" },
  error: { label: "读取失败", tone: "bg-red-50 text-red-700 border-red-200" },
  not_required: { label: "无需登录", tone: "bg-wash text-muted border-line" },
};

const LOGIN_TEXT: Record<string, string> = {
  idle: "还没有打开登录窗口",
  opened: "登录窗口已打开，等你在 Chrome 里扫码",
  waiting: "窗口开着，还没检测到登录态",
  ok: "登录成功，cookie 已保存",
  closed: "登录窗口被关掉了，可以重新打开",
  error: "登录流程出错",
};

const RUN_STATUS: Record<string, { label: string; tone: string }> = {
  running: { label: "进行中", tone: "border-amber-200 text-amber-700 dark:border-amber-500/30 dark:text-amber-300" },
  done: { label: "已完成", tone: "border-emerald-200 text-emerald-700 dark:border-emerald-500/30 dark:text-emerald-300" },
  error: { label: "出错了", tone: "border-red-200 text-red-700 dark:border-red-500/30 dark:text-red-300" },
  cancelled: { label: "已取消", tone: "border-line text-muted" },
};

/** 能撤销的动作；别的一律不显示按钮 */
const UNDO_TEXT: Record<string, string> = {
  save_item: "撤销收藏",
  mark_read: "撤销标记",
  export_markdown: "删掉导出的文件",
};

const EASE = [0.22, 1, 0.36, 1] as const;

/** 三档粒度。hint 会跟着选中项换，让人知道换档到底换到了什么。 */
const DEPTH_OPTIONS = [
  { id: "brief", label: "简洁", hint: "两三条要点，只留最关键的那句。适合先扫一眼。" },
  { id: "balanced", label: "平衡", hint: "默认。覆盖全片，一条要点说一件事，2–6 条。" },
  { id: "detailed", label: "详细", hint: "写全：6–10 条，关键数字、结论、争议点都展开。慢一点，token 也贵一点。" },
] as const;

export default function SettingsPage({ ctx }: { ctx: OutletCtx }) {
  useEffect(() => {
    document.title = "设置 · OneFeed";
  }, []);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState("");
  const [plugins, setPlugins] = useState<PluginsResponse | null>(null);
  const [auth, setAuth] = useState<Record<string, AuthState>>({});
  const [authRows, setAuthRows] = useState<string[]>([]);
  const [login, setLogin] = useState<Record<string, LoginStatus>>({});
  const [note, setNote] = useState("");
  const [form, setForm] = useState<SettingsValues | null>(null);
  const [baseline, setBaseline] = useState("");
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({ status: true, ai: true, agent: true });
  const [active, setActive] = useState("status");
  const [runs, setRuns] = useState<AgentRunRow[]>([]);
  const reduce = useReducedMotion();
  const copyTimer = useRef(0);
  const formRef = useRef<SettingsValues | null>(null);
  const navigate = useNavigate();
  // 没保存就站内离开时的三道拦截：链接点击、浏览器返回、关标签页（beforeunload 在下面）
  const dirtyRef = useRef(false);
  const leavingRef = useRef(false);
  const leaveBusyRef = useRef(false);
  const guardDepthRef = useRef(0);
  const guardRef = useRef<(to: string) => void>(() => {});

  const load = useCallback(async () => {
    // health 是最先能返回的一块：单独请求，别等插件/设置/登录全齐才显示；
    // 更不能用 0 冒充“还没回来”。
    setHealthError("");
    getJSON<Health>("/api/health")
      .then((h) => {
        setHealth(h);
      })
      .catch((err: Error) => {
        setHealthError(err.message);
      });
    try {
      const [p, s, rowsResp] = await Promise.all([
        getJSON<PluginsResponse>("/api/plugins"),
        getJSON<SettingsResponse>("/api/settings"),
        fetchAuthRows().catch(() => ({ rows: [] as AuthRow[] })),
      ]);
      setPlugins(p);
      // 先摊平冷却表：默认是空的（= 全用内置默认），用户要看到真实的「B 站 5 分钟」。
      const merged: SettingsValues = {
        ...s.settings,
        platform_intervals: { ...(s.intervals ?? {}), ...(s.settings.platform_intervals ?? {}) },
      };
      // 没有未保存改动时才跟随外部设置刷新；有改动就以用户正在编辑的值为准。
      if (!formRef.current || !dirtyRef.current) {
        formRef.current = merged;
        setForm(merged);
        setBaseline(JSON.stringify(merged));
      }
      // 行清单以后端 /api/auth 为准：有登录流程的平台由后端登记，前端别再抄一份名单。
      // 老后端没有该接口时退回已装插件，至少不会把整个登录区弄没。
      const candidates = rowsResp.rows.length ? rowsResp.rows.map((r) => r.plugin) : p.installed.map((i) => i.id);
      const states = await Promise.all(
        candidates.map((id) =>
          getJSON<AuthState>("/api/auth/" + id).catch((err: Error): AuthState => ({ plugin: id, state: "error", message: err.message })),
        ),
      );
      const map: Record<string, AuthState> = {};
      for (const s2 of states) map[s2.plugin] = s2;
      setAuth(map);
      setAuthRows(states.filter((st) => st.can_login || st.cli).map((st) => st.plugin));
    } catch (err) {
      setNote((err as Error).message);
    }
  }, []);

  useEffect(() => {
    formRef.current = form;
  }, [form]);

  useEffect(() => {
    void load();
  }, [load, ctx.reloadKey]);

  // 左侧导航跟着滚动高亮：拿每个 section 的当前位置算，不用 IntersectionObserver 的一堆阈值。
  useEffect(() => {
    const onScroll = () => {
      let current = SECTIONS[0].id;
      for (const s of SECTIONS) {
        const el = document.getElementById(s.id);
        if (el && el.getBoundingClientRect().top <= 132) current = s.id;
      }
      setActive(current);
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const loadRuns = useCallback(async () => {
    try {
      const data = await agentRuns(8);
      setRuns(data.runs ?? []);
    } catch {
      // 后端没开 Agent 或读不到时不要把整页搞挂
      setRuns([]);
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns, ctx.reloadKey]);

  const flash = (text: string) => {
    setNote(text);
    window.clearTimeout(copyTimer.current);
    copyTimer.current = window.setTimeout(() => setNote(""), 3200);
  };

  const undo = async (token: string, text: string) => {
    try {
      const resp = await agentUndo(token);
      if (resp.ok === false) {
        flash(String(resp.error ?? "撤销失败"));
        return;
      }
      flash(resp.note ? text + "：" + String(resp.note) : text);
      await loadRuns();
      ctx.bump();
    } catch (err) {
      flash((err as Error).message);
    }
  };

  const toggle = async (id: string, enabled: boolean) => {
    // 先本地翻一次：开关要跟手，失败再翻回去并说明原因
    setPlugins((prev) =>
      prev ? { ...prev, installed: prev.installed.map((p) => (p.id === id ? { ...p, enabled: enabled ? 1 : 0 } : p)) } : prev,
    );
    try {
      const resp = await fetch("/api/plugins/" + encodeURIComponent(id), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!resp.ok) throw new Error("后端拒绝了这次切换（HTTP " + resp.status + "）");
      flash(enabled ? "已启用 " + id : "已停用 " + id);
      void load();
      ctx.bump();
    } catch (err) {
      setPlugins((prev) =>
        prev
          ? { ...prev, installed: prev.installed.map((p) => (p.id === id ? { ...p, enabled: enabled ? 0 : 1 } : p)) }
          : prev,
      );
      flash((err as Error).message);
    }
  };

  const dirty = Boolean(form && baseline && JSON.stringify(form) !== baseline);

  useEffect(() => {
    dirtyRef.current = dirty;
  }, [dirty]);

  // 关标签页 / 刷新时别把没保存的改动悄悄丢掉
  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [dirty]);

  const saveSettings = async (): Promise<boolean> => {
    if (!form) return false;
    setSaving(true);
    try {
      // 空 key 表示「不改」，不要把已存的 key 冲掉；要清有单独的按钮。
      const payload: Record<string, unknown> = { ...form, ai_providers: form.ai_providers ?? [] };
      if (!form.ai_api_key.trim()) delete payload.ai_api_key;
      const resp = await putJSON<{ ok: boolean; settings: SettingsValues; applied: string[]; resolved: SettingsResponse["resolved"] }>(
        "/api/settings",
        payload,
      );
      setForm(resp.settings);
      setBaseline(JSON.stringify(resp.settings));
      await ctx.reloadSettings();
      flash(resp.applied?.length ? "已保存：" + resp.applied.join("；") : "已保存");
      void load();
      return true;
    } catch (err) {
      flash((err as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  };

  // 三选：保存 / 不保存 / 取消。选「保存」等它真的落盘成功才走，失败就留在原地。
  const askLeave = async (to: string) => {
    if (leaveBusyRef.current) return;
    if (!dirtyRef.current) {
      if (to) navigate(to);
      return;
    }
    leaveBusyRef.current = true;
    try {
      const choice = await choiceDialog({
        title: "这些设置还没保存",
        body: "离开前保存吗？不保存的话，这次改的内容会恢复成上次保存的值。",
        confirmText: "保存并离开",
        secondaryText: "不保存",
        cancelText: "取消",
      });
      if (choice === "cancel") return;
      if (choice === "confirm") {
        const ok = await saveSettings();
        if (!ok) return;
      }
      dirtyRef.current = false;
      leavingRef.current = true;
      if (to) {
        navigate(to);
        return;
      }
      // 浏览器返回：脏的时候压过 guardDepthRef 条哨兵，一次退回到进设置页之前
      window.history.go(-(guardDepthRef.current + 1));
      window.setTimeout(() => {
        if (window.location.pathname === "/settings") {
          leavingRef.current = false;
          navigate("/");
        }
      }, 700);
    } finally {
      leaveBusyRef.current = false;
    }
  };
  guardRef.current = (to) => void askLeave(to);

  // 拦站内链接：React Router 的 Link/NavLink 最终也是 <a href>，在 document 捕获阶段先接管
  useEffect(() => {
    if (!dirty) return;
    const onClick = (e: MouseEvent) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const anchor = (e.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
      if (!anchor || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
      const url = new URL(anchor.href, window.location.href);
      if (url.origin !== window.location.origin) return;
      if (url.pathname === window.location.pathname && url.search === window.location.search) return;
      e.preventDefault();
      e.stopPropagation();
      guardRef.current(url.pathname + url.search + url.hash);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [dirty]);

  // 浏览器返回：脏的时候往历史里压一条同页哨兵，让「返回」先回到这条哨兵上再问
  useEffect(() => {
    if (!dirty) return;
    guardDepthRef.current += 1;
    const mask = { ...(window.history.state ?? {}), __ofSettingsGuard: true };
    window.history.pushState(mask, "", window.location.href);
    const onPop = () => {
      if (leavingRef.current) return;
      window.history.pushState(mask, "", window.location.href);
      guardRef.current("");
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [dirty]);

  const clearKeys = async () => {
    const ok = await confirmDialog({
      title: "清除所有模型 key？",
      body: "AI 会退回本地关键词解析，摘要与 Agent 功能将不可用。key 不会留在本机，只能重新填写。",
      confirmText: "清除",
      tone: "danger",
      requireTyping: "CLEAR",
    });
    if (!ok) return;
    try {
      await putJSON("/api/settings", { ai_api_key: "", ai_providers: [] });
      // baseline 必须跟着新值走：写成空字符串会让 dirty 恒为 false，之后改任何设置都不再提示保存
      setForm((prev) => {
        if (!prev) return prev;
        const next = { ...prev, ai_api_key: "", ai_providers: [] };
        setBaseline(JSON.stringify(next));
        return next;
      });
      await ctx.reloadSettings();
      flash("已清除所有模型 key，AI 退回本地解析");
    } catch (err) {
      flash((err as Error).message);
    }
  };

  const startLogin = async (id: string) => {
    try {
      const resp = await postJSON<{ ok: boolean; login: LoginStatus }>("/api/auth/" + id + "/login");
      setLogin((prev) => ({ ...prev, [id]: { ...resp.login, plugin: id } }));
      flash("登录窗口已打开：在弹出来的 Chrome 里扫码，扫完点「我已完成登录」");
    } catch (err) {
      setLogin((prev) => ({ ...prev, [id]: { plugin: id, state: "error", message: (err as Error).message } }));
    }
  };

  const checkLogin = async (id: string) => {
    try {
      const st = await getJSON<LoginStatus>("/api/auth/" + id + "/login/status");
      setLogin((prev) => ({ ...prev, [id]: { ...st, plugin: id } }));
      if (st.state === "ok") {
        flash("登录成功，cookie 已写入本机");
        void load();
        void ctx.bump();
      } else {
        flash(LOGIN_TEXT[st.state] ?? "还没检测到登录态");
      }
    } catch (err) {
      flash((err as Error).message);
    }
  };

  const logout = async (id: string) => {
    const ok = await confirmDialog({
      title: "退出这个平台的登录？",
      body: "本机保存的 cookie 会被删除，之后刷新这个平台要重新扫码。",
      confirmText: "退出登录",
      tone: "danger",
    });
    if (!ok) return;
    try {
      await postJSON("/api/auth/" + id + "/logout");
      setLogin((prev) => ({ ...prev, [id]: { plugin: id, state: "idle" } }));
      flash("已退出并删除本机 cookie");
      void load();
      void ctx.bump();
    } catch (err) {
      flash((err as Error).message);
    }
  };

  const pendingKey = useMemo(
    () =>
      Object.entries(login)
        .filter(([, s]) => s.state === "opened" || s.state === "waiting")
        .map(([id]) => id)
        .sort()
        .join(","),
    [login],
  );

  const loadRef = useRef(load);
  loadRef.current = load;
  const bumpRef = useRef(ctx.bump);
  bumpRef.current = ctx.bump;

  useEffect(() => {
    if (!pendingKey) return;
    const ids = pendingKey.split(",");
    const timer = window.setInterval(() => {
      for (const id of ids) {
        void getJSON<LoginStatus>("/api/auth/" + id + "/login/status")
          .then((st) => {
            setLogin((prev) => ({ ...prev, [id]: { ...st, plugin: id } }));
            if (st.state === "ok") {
              setNote("登录成功，cookie 已写入本机");
              void loadRef.current();
              bumpRef.current();
            }
          })
          .catch(() => undefined);
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [pendingKey]);

  const copy = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      flash("已复制 " + label);
    } catch {
      flash("复制失败，请手动输入：" + text);
    }
  };

  const defaults = ctx.settings?.defaults;
  const resolved = ctx.settings?.resolved;
  const ai = ctx.settings?.ai;
  const providerCount = form?.ai_providers?.length ?? 0;
  const authReady = authRows.filter((id) => auth[id]?.state === "available").length;
  const installed = plugins?.installed ?? [];
  const enabledCount = installed.filter((p) => p.enabled).length;

  const jump = (id: string) => {
    setOpen((prev) => ({ ...prev, [id]: true }));
    window.setTimeout(() => {
      document.getElementById(id)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    }, reduce ? 0 : 340);
  };

  return (
    <div className="pb-28 pt-6">
      <h1 className="font-display text-[19px] font-semibold tracking-tight">设置</h1>

      <div className="mt-6 grid gap-6 lg:grid-cols-[184px_minmax(0,1fr)]">
        <nav aria-label="设置分类" className="hidden lg:block">
          <div className="sticky top-[76px] space-y-0.5">
            {SECTIONS.map((s) => (
              <button
                key={s.id}
                onClick={() => jump(s.id)}
                className={
                  "flex w-full items-center rounded-lg px-2.5 py-1.5 text-left text-[13px] transition-colors " +
                  (active === s.id ? "nav-active font-medium" : "text-muted hover:bg-wash/60 hover:text-ink")
                }
              >
                {s.label}
              </button>
            ))}
          </div>
        </nav>

        <div className="min-w-0 space-y-3">
          <AnimatePresence initial={false}>
            {dirty ? (
              <motion.div
                key="dirty"
                initial={{ opacity: 0, y: 14, scale: 0.98, x: "-50%" }}
                animate={{ opacity: 1, y: 0, scale: 1, x: "-50%" }}
                exit={{ opacity: 0, y: 14, scale: 0.98, x: "-50%" }}
                transition={{ duration: reduce ? 0 : 0.24, ease: EASE }}
                className="fixed bottom-6 left-1/2 z-40"
              >
                <div className="flex items-center gap-2 rounded-full border border-line bg-paper px-2 py-1.5 pl-4 shadow-[0_12px_34px_rgba(26,22,14,0.16)]">
                  <span className="text-[13px] text-ink">有未保存的改动</span>
                  <button
                    onClick={() => void saveSettings()}
                    disabled={saving}
                    className="ml-auto flex h-8 items-center gap-1.5 rounded-lg bg-solid px-3 text-[13px] text-solid-fg disabled:opacity-60"
                  >
                    <Save size={12} />
                    {saving ? "保存中…" : "保存"}
                  </button>
                  <button
                    onClick={() => {
                      if (baseline) setForm(JSON.parse(baseline) as SettingsValues);
                    }}
                    className="flex h-8 items-center gap-1.5 rounded-lg border border-line bg-paper px-2.5 text-[12px] text-muted hover:text-ink"
                  >
                    <RotateCcw size={12} />
                    放弃
                  </button>
                </div>
              </motion.div>
            ) : null}
          </AnimatePresence>

          <SettingSection
            id="status"
            title="运行状态"
            desc="版本与条目数"
            summary={
              health ? (
                <>
                  <span>{health.items} 条</span>
                  <span className="text-fade">·</span>
                  <span>{health.plugins} 个插件</span>
                  <span className="text-fade">·</span>
                  <span>v{health.version}</span>
                </>
              ) : (
                <span className={healthError ? "text-danger" : "text-fade"}>
                  {healthError ? "状态没取到" : "检查中…"}
                </span>
              )
            }
            open={Boolean(open.status)}
            onToggle={() => setOpen((prev) => ({ ...prev, status: !prev.status }))}
          >
            <dl
              className="grid grid-cols-2 gap-x-6 gap-y-2 text-[13px]"
              aria-busy={!health && !healthError}
            >
              <div className="flex justify-between">
                <dt className="text-fade">版本</dt>
                <dd>{health ? health.version : healthError ? "—" : "检查中…"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-fade">条目</dt>
                <dd>{health ? health.items : healthError ? "—" : "检查中…"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-fade">插件</dt>
                <dd>{health ? health.plugins : healthError ? "—" : "检查中…"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-fade">模式</dt>
                <dd>{health ? (health.demo ? "离线演示" : "联网") : healthError ? "—" : "检查中…"}</dd>
              </div>
            </dl>
            {healthError ? (
              <p className="mt-2 text-[12px] leading-relaxed text-danger">状态没取到：{healthError}</p>
            ) : null}
            <div className="mt-3 flex gap-2">
              <button onClick={ctx.refresh} className="flex h-9 items-center gap-1.5 rounded-lg bg-solid px-3.5 text-[13px] text-solid-fg">
                <RefreshCw size={13} />
                现在刷新一轮
              </button>
              <button onClick={() => void load()} className="flex h-9 items-center gap-1.5 rounded-lg border border-line px-3.5 text-[13px] text-muted hover:text-ink">
                重新检查
              </button>
            </div>
          </SettingSection>

          <SettingSection
            id="collect"
            title="采集与排序"
            desc="每轮条数、保留天数、自动更新"
            summary={
              <>
                <span>{form?.per_plugin_limit ?? "—"} 条/平台</span>
                <span className="text-fade">·</span>
                <span>保留 {form?.prune_days ?? "—"} 天</span>
                <span className="text-fade">·</span>
                <span>{form?.auto_update ? "自动更新插件" : "不自动更新"}</span>
              </>
            }
            open={Boolean(open.collect)}
            onToggle={() => setOpen((prev) => ({ ...prev, collect: !prev.collect }))}
          >
            {form ? (
              <div className="mt-4 space-y-4">
                <label className="block">
                  <span className="text-[13px] font-medium">插件目录</span>
                  <input
                    value={form.plugins_dir}
                    onChange={(e) => setForm({ ...form, plugins_dir: e.target.value })}
                    placeholder={resolved?.plugins_dir ?? ""}
                    className="mt-1.5 h-9 w-full rounded-lg border border-line bg-paper px-3 font-mono text-[12px] outline-none focus:border-ink/40"
                  />
                  <span className="mt-1 block text-[11px] text-fade">留空用默认目录</span>
                </label>

                <label className="block">
                  <span className="text-[13px] font-medium">插件市场 registry 地址</span>
                  <input
                    value={form.registry_url}
                    onChange={(e) => setForm({ ...form, registry_url: e.target.value })}
                    placeholder={resolved?.registry_url ?? ""}
                    className="mt-1.5 h-9 w-full rounded-lg border border-line bg-paper px-3 font-mono text-[12px] outline-none focus:border-ink/40"
                  />
                  <span className="mt-1 block text-[11px] text-fade">留空用默认订阅源</span>
                </label>

                <div className="grid grid-cols-2 gap-4">
                  <label className="block">
                    <span className="text-[13px] font-medium">每平台每轮条数</span>
                    <NumberField
                      value={form.per_plugin_limit}
                      min={1}
                      max={50}
                      onChange={(next) => setForm({ ...form, per_plugin_limit: next })}
                    />
                  </label>
                  <label className="block">
                    <span className="text-[13px] font-medium">详情页评论条数</span>
                    <NumberField
                      value={form.comments_limit}
                      min={1}
                      max={50}
                      onChange={(next) => setForm({ ...form, comments_limit: next })}
                    />
                  </label>
                  <label className="block">
                    <span className="text-[13px] font-medium">默认排序</span>
                    <select
                      value={form.default_sort}
                      onChange={(e) => setForm({ ...form, default_sort: e.target.value })}
                      className="mt-1.5 h-9 w-full rounded-lg border border-line bg-paper px-2.5 text-[13px] outline-none focus:border-ink/40"
                    >
                      {(ctx.settings?.sorts ?? ["freshness", "engagement"]).map((s) => (
                        <option key={s} value={s}>
                          {s === "freshness" ? "按新鲜度" : s === "engagement" ? "按热度" : s}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block">
                    <span className="text-[13px] font-medium">本地保留天数</span>
                    <NumberField
                      value={form.prune_days}
                      min={1}
                      max={365}
                      onChange={(next) => setForm({ ...form, prune_days: next })}
                    />
                  </label>
                </div>

                <label className="block max-w-[280px]">
                  <span className="text-[13px] font-medium">关注页布局</span>
                  <select
                    value={form.following_layout ?? "list"}
                    onChange={(e) => setForm({ ...form, following_layout: e.target.value })}
                    className="mt-1.5 h-9 w-full rounded-lg border border-line bg-paper px-2.5 text-[13px] outline-none focus:border-ink/40"
                  >
                    <option value="list">列表 · 按日期</option>
                    <option value="timeline">时间线 · 按作者</option>
                    <option value="compact">紧凑 · 双列</option>
                  </select>
                  <span className="mt-1 block text-[11px] text-fade">
                    关注页顶部也能临时切换；这里决定下次打开时的默认布局。
                  </span>
                </label>

                <div className="rounded-lg border border-line px-3.5 py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-[13px] font-medium">平台抓取间隔</span>
                    <span className="text-[11px] text-fade">单位：分钟 · 0 = 不限制</span>
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-fade">
                    同一个平台两次抓取之间至少隔这么久。抓太密容易撞上平台风控，
                    被限流时接口会返回空列表，看起来就像「这个平台今天没内容」。
                    手点刷新也受这个限制；真急着抓，可在刷新完成的提示里点「仍要抓」。
                  </p>
                  <div className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-2.5 sm:grid-cols-3">
                    {PLATFORMS.map((p) => (
                      <label key={p.id} className="block">
                        <span className="text-[12px] text-muted">{p.label}</span>
                        <input
                          type="number"
                          min={0}
                          max={1440}
                          step={1}
                          aria-label={p.label + " 抓取间隔（分钟）"}
                          value={Math.round((form.platform_intervals[p.id] ?? 0) / 60)}
                          onChange={(e) => {
                            const raw = e.target.value;
                            const minutes =
                              raw === "" ? 0 : Math.max(0, Math.min(1440, Math.round(Number(raw) || 0)));
                            setForm({
                              ...form,
                              platform_intervals: { ...form.platform_intervals, [p.id]: minutes * 60 },
                            });
                          }}
                          className="mt-1.5 h-9 w-full rounded-lg border border-line bg-paper px-3 text-[13px] outline-none focus:border-ink/40"
                        />
                      </label>
                    ))}
                  </div>
                </div>

                <label className="flex items-start gap-2.5 rounded-lg border border-line px-3.5 py-3">
                  <input
                    type="checkbox"
                    checked={form.auto_update}
                    onChange={(e) => setForm({ ...form, auto_update: e.target.checked })}
                    className="mt-0.5 h-4 w-4 accent-black"
                  />
                  <span>
                    <span className="text-[13px] font-medium">每轮采集前自动更新插件</span>
                    <span className="mt-0.5 block text-[11px] leading-relaxed text-fade">
                      每轮采集前先查一次市场，有新版自动更新。
                    </span>
                  </span>
                </label>

                <label className="flex items-start gap-2.5 rounded-lg border border-line px-3.5 py-3">
                  <input
                    type="checkbox"
                    checked={form.agent_auto_pull}
                    onChange={(e) => setForm({ ...form, agent_auto_pull: e.target.checked })}
                    className="mt-0.5 h-4 w-4 accent-black"
                  />
                  <span>
                    <span className="text-[13px] font-medium">Agent 搜不到时自动抓一轮</span>
                    <span className="mt-0.5 block text-[11px] leading-relaxed text-fade">
                      库里 0 条时先去平台抓一轮再查；每轮最多一次，仍受上面的抓取间隔限制。
                    </span>
                  </span>
                </label>

                <div className="flex items-center gap-2 pt-1">
                  <button
                    onClick={() => void saveSettings()}
                    disabled={saving}
                    className="flex h-9 items-center gap-1.5 rounded-lg bg-solid px-4 text-[13px] text-solid-fg disabled:opacity-60"
                  >
                    <Save size={13} />
                    {saving ? "保存中…" : "保存设置"}
                  </button>
                  <button
                    onClick={async () => {
                      if (!defaults) return;
                      const ok = await confirmDialog({
                        title: "把设置改回默认值？",
                        body: "表单会重置，包括刚才改了还没保存的内容。",
                        confirmText: "恢复默认",
                      });
                      if (ok) setForm({ ...defaults });
                    }}
                    className="h-9 rounded-lg border border-line px-3.5 text-[13px] text-muted hover:text-ink"
                  >
                    恢复默认值
                  </button>
                  <span className="ml-auto truncate text-[11px] text-fade">状态目录：{resolved?.state_dir ?? "—"}</span>
                </div>
              </div>
            ) : (
              <div className="mt-3 min-h-[420px] animate-pulse space-y-3">
                {[0, 1, 2, 3, 4, 5].map((i) => (
                  <div key={i} className="h-9 rounded-lg bg-wash" />
                ))}
              </div>
            )}
          </SettingSection>

          <SettingSection
            id="ai"
            title="AI 助手"
            desc="按顺序试多个模型，前面的挂了自动换下一个"
            summary={
              <>
                <span className="rounded-full border border-line px-1.5 py-0.5 text-[11px]">
                  {ai?.agent ? "Agent 在线" : ai?.engine === "llm" ? "模型在线" : "本地兜底"}
                </span>
                <span>{providerCount ? providerCount + " 个模型" : "还没配 key"}</span>
                {ai?.active ? (
                  <>
                    <span className="text-fade">·</span>
                    <span className="text-ink">{ai.active}</span>
                  </>
                ) : null}
              </>
            }
            open={Boolean(open.ai)}
            onToggle={() => setOpen((prev) => ({ ...prev, ai: !prev.ai }))}
          >
            {form ? (
              <div className="mt-4 space-y-4">
                <AiProviders
                  value={form.ai_providers ?? []}
                  onChange={(next) => setForm({ ...form, ai_providers: next })}
                  status={ai}
                />
                <div className="rounded-lg border border-line px-3.5 py-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="text-[13px] font-medium">默认总结粒度</span>
                    <span className="text-[11px] text-fade">详情页里还能逐条临时改</span>
                  </div>
                  <div
                    role="group"
                    aria-label="默认总结粒度"
                    className="mt-2 inline-flex rounded-full border border-line p-0.5 text-[12px]"
                  >
                    {DEPTH_OPTIONS.map((option) => {
                      const on = (form.summary_depth ?? "balanced") === option.id;
                      return (
                        <button
                          key={option.id}
                          type="button"
                          onClick={() => setForm({ ...form, summary_depth: option.id })}
                          aria-pressed={on}
                          className={
                            "relative rounded-full px-3 py-1 transition-colors duration-150 " +
                            (on ? "text-ink" : "text-muted hover:text-ink")
                          }
                        >
                          {on ? (
                            <motion.span
                              layoutId="settings-depth-pill"
                              className="absolute inset-0 rounded-full bg-wash ring-1 ring-inset ring-line"
                              transition={{ duration: reduce ? 0 : 0.24, ease: EASE }}
                            />
                          ) : null}
                          <span className="relative">{option.label}</span>
                        </button>
                      );
                    })}
                  </div>
                  <p className="mt-1.5 text-[11px] leading-relaxed text-fade">
                    {DEPTH_OPTIONS.find((o) => o.id === (form.summary_depth ?? "balanced"))?.hint}
                  </p>
                </div>

                <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-line px-3.5 py-3">
                  <input
                    type="checkbox"
                    checked={form.vision_summary}
                    onChange={(e) => setForm({ ...form, vision_summary: e.target.checked })}
                    className="mt-0.5 h-4 w-4 accent-black"
                  />
                  <span>
                    <span className="text-[13px] font-medium">总结时读图</span>
                    <span className="mt-0.5 block text-[11px] leading-relaxed text-fade">
                      图文笔记取前三张、视频取封面一起交给多模态模型；关掉只读文字，省 token。
                    </span>
                  </span>
                </label>
                <div className="flex items-center gap-2">
                  <button onClick={() => void clearKeys()} className="ml-auto h-8 rounded-lg border border-line px-3 text-[12px] text-muted hover:text-ink">
                    清除所有 key
                  </button>
                </div>
              </div>
            ) : null}
          </SettingSection>

          <SettingSection
            id="agent"
            title="Agent 活动"
            desc="最近跑过的指令与它们改过的东西；收藏、标记、导出的文件都能在这里撤回"
            summary={
              <>
                <span>{runs.length ? "最近 " + runs.length + " 轮" : "还没有记录"}</span>
                <span className="text-fade">·</span>
                <span>留在本机，不上传</span>
              </>
            }
            open={Boolean(open.agent)}
            onToggle={() => setOpen((prev) => ({ ...prev, agent: !prev.agent }))}
          >
            {runs.length === 0 ? (
              <p className="mt-3 text-[12px] text-fade">在右下角问一句，跑完这里会留下轨迹和撤销入口。</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {runs.map((run) => {
                  const status = RUN_STATUS[run.status] ?? RUN_STATUS.done;
                  const undos = (run.events ?? []).filter(
                    (e) => e.kind === "action" && e.undo_token && UNDO_TEXT[e.name],
                  );
                  return (
                    <li key={run.id} className="rounded-lg border border-line px-3.5 py-3">
                      <div className="flex flex-wrap items-baseline gap-2">
                        <span className="text-[11px] text-fade">{timeAgo(run.created_at)}</span>
                        <span className="min-w-0 flex-1 truncate text-[13px] text-ink">{run.input || "（空指令）"}</span>
                        <span className={"rounded-full border px-1.5 py-0.5 text-[11px] " + status.tone}>{status.label}</span>
                      </div>
                      {run.status === "error" ? (
                        <p className="mt-1 text-[12px] text-red-600 dark:text-red-400">{run.error || "没有留下错误信息"}</p>
                      ) : run.reply ? (
                        <p className="mt-1 line-clamp-2 text-[12px] text-muted">{run.reply}</p>
                      ) : null}
                      {undos.length ? (
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          {undos.map((e) => (
                            <button
                              key={e.seq}
                              onClick={() => void undo(e.undo_token as string, UNDO_TEXT[e.name])}
                              title={e.name === "export_markdown" ? String(e.data?.path ?? "") : undefined}
                              className="flex h-7 items-center gap-1 rounded-md border border-line px-2 text-[12px] text-muted hover:text-red-600"
                            >
                              <RotateCcw size={11} />
                              {UNDO_TEXT[e.name]}
                            </button>
                          ))}
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </SettingSection>

          <SettingSection
            id="auth"
            title="登录态"
            desc={authRows.length ? authRows.map((id) => platform(id).label).join("、") : "检查各平台的登录状态"}
            summary={
              <>
                <span>{authReady} 个平台已登录</span>
                <span className="text-fade">·</span>
                <span>cookie 只存本机</span>
              </>
            }
            open={Boolean(open.auth)}
            onToggle={() => setOpen((prev) => ({ ...prev, auth: !prev.auth }))}
          >
            <p className="text-[12px] text-fade">登录窗口是独立的 Chrome，登录完会自动关掉。</p>
            <ul className="mt-3 space-y-2">
              {authRows.map((id) => {
                const state = auth[id];
                const meta = STATE_TEXT[state?.state ?? "need_login"] ?? STATE_TEXT.need_login;
                const pending = login[id]?.state === "opened" || login[id]?.state === "waiting";
                const isCli = Boolean(state?.cli);
                return (
                  <li key={id} className="rounded-lg border border-line px-3.5 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="h-[7px] w-[7px] rounded-full" style={{ background: platform(id).tint }} />
                      <span className="text-[13px] font-medium">{platform(id).label}</span>
                      <span className={"rounded-full border px-1.5 py-0.5 text-[11px] " + meta.tone}>{meta.label}</span>
                      {state?.cookies ? <span className="text-[11px] text-fade">{state.cookies} 个 cookie</span> : null}
                      <span className="ml-auto flex items-center gap-1.5">
                        {isCli ? (
                          <button
                            onClick={() => void copy(state?.command || "bili login", "命令")}
                            className="flex h-7 items-center gap-1 rounded-md border border-line px-2 text-[12px] text-muted hover:text-ink"
                          >
                            <Copy size={11} />
                            复制 bili login
                          </button>
                        ) : null}
                        {state?.can_login ? (
                          <>
                            <button
                              onClick={() => void startLogin(id)}
                              className="flex h-7 items-center gap-1 rounded-md bg-solid px-2.5 text-[12px] text-solid-fg"
                            >
                              <LogIn size={11} />
                              打开登录窗口
                            </button>
                            <button
                              onClick={() => void checkLogin(id)}
                              className="flex h-7 items-center gap-1 rounded-md border border-line px-2 text-[12px] text-muted hover:text-ink"
                            >
                              <RefreshCw size={11} className={pending ? "animate-spin" : ""} />
                              我已完成登录
                            </button>
                            {state?.state === "available" ? (
                              <button
                                onClick={() => void logout(id)}
                                className="flex h-7 items-center gap-1 rounded-md border border-line px-2 text-[12px] text-muted hover:text-red-600"
                              >
                                <LogOut size={11} />
                                退出
                              </button>
                            ) : null}
                          </>
                        ) : null}
                      </span>
                    </div>
                    <p className="mt-1.5 text-[12px] leading-relaxed text-muted">
                      {login[id] ? LOGIN_TEXT[login[id].state] + (login[id].message ? " · " + login[id].message : "") : state?.message || "还没检查"}
                    </p>
                    {state?.hint && !login[id] && state.hint !== state.message ? <p className="mt-1 text-[12px] text-fade">{state.hint}</p> : null}
                    {isCli && state?.command ? (
                      <p className="mt-1 font-mono text-[12px] text-fade">
                        $ {state.command}
                        {state.login_url ? (
                          <a href={state.login_url} target="_blank" rel="noreferrer" className="ml-2 inline-flex items-center gap-0.5 text-muted hover:underline">
                            打开 <ExternalLink size={10} />
                          </a>
                        ) : null}
                      </p>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          </SettingSection>

          <SettingSection
            id="plugins"
            title="已装插件"
            desc="启用或停用某个平台"
            summary={
              <>
                <span>{installed.length} 个</span>
                <span className="text-fade">·</span>
                <span>{enabledCount} 个在用</span>
              </>
            }
            open={Boolean(open.plugins)}
            onToggle={() => setOpen((prev) => ({ ...prev, plugins: !prev.plugins }))}
          >
            <ul className="divide-y divide-line">
              {installed.map((p) => (
                <li key={p.id} className="flex items-center gap-2.5 py-2.5">
                  <span className="h-[7px] w-[7px] rounded-full" style={{ background: platform(p.id).tint }} />
                  <span className="text-[13px]">{p.name || platform(p.id).label}</span>
                  <span className="text-[11px] text-fade">v{p.version}</span>
                  {p.features?.includes("comments") ? (
                    <span className="rounded-full bg-emerald-50 dark:bg-emerald-500/10 px-1.5 py-0.5 text-[11px] text-emerald-700 dark:text-emerald-300">评论区</span>
                  ) : (
                    <span className="rounded-full bg-wash px-1.5 py-0.5 text-[11px] text-fade">无评论</span>
                  )}
                  <span className="text-[11px] text-fade">{p.source === "registry" ? "市场安装" : "本地"}</span>
                  <button
                    onClick={() => void toggle(p.id, !p.enabled)}
                    role="switch"
                    aria-checked={Boolean(p.enabled)}
                    aria-label={(p.name || platform(p.id).label) + (p.enabled ? "：已启用" : "：已停用")}
                    className={"ml-auto h-6 w-11 rounded-full p-0.5 transition " + (p.enabled ? "bg-solid" : "bg-line")}
                    title={p.enabled ? "点击停用" : "点击启用"}
                  >
                    <span className={"block h-5 w-5 rounded-full bg-paper shadow transition-transform duration-200 " + (p.enabled ? "translate-x-5" : "translate-x-0")} />
                  </button>
                </li>
              ))}
              {!installed.length ? <li className="py-3 text-[13px] text-muted">还没装插件，去市场挑两个。</li> : null}
            </ul>
            {plugins?.errors?.length ? <p className="mt-2 text-[12px] text-amber-600 dark:text-amber-300">有插件加载失败：{plugins.errors.join("；")}</p> : null}
          </SettingSection>

        </div>
      </div>

      <AnimatePresence>
        {note ? (
          <motion.div
            key="note"
            role="status"
            aria-live="polite"
            initial={{ opacity: 0, y: 10, scale: 0.98, x: "-50%" }}
            animate={{ opacity: 1, y: 0, scale: 1, x: "-50%" }}
            exit={{ opacity: 0, y: 10, scale: 0.98, x: "-50%" }}
            transition={{ duration: reduce ? 0 : 0.2, ease: EASE }}
            className="fixed bottom-24 left-1/2 z-50 rounded-full bg-solid px-5 py-2.5 text-[13px] text-solid-fg shadow-pop"
          >
            {note}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
