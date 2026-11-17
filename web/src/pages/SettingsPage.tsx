import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Copy, ExternalLink, LogIn, LogOut, RefreshCw, RotateCcw, Save, ShieldCheck } from "lucide-react";
import type { OutletCtx } from "../App";
import {
  getJSON,
  postJSON,
  putJSON,
  type AuthState,
  type Health,
  type LoginStatus,
  type PluginsResponse,
  type SettingsResponse,
  type SettingsValues,
} from "../api";
import { platform } from "../platform";
import SettingSection from "../components/SettingSection";
import AiProviders from "../components/AiProviders";

const AUTH_PLUGINS = ["xiaohongshu", "douyin"];
const ALL_AUTH_ROWS = [...AUTH_PLUGINS, "bilibili"];

const SECTIONS = [
  { id: "status", label: "运行状态" },
  { id: "collect", label: "采集与排序" },
  { id: "ai", label: "AI 助手" },
  { id: "auth", label: "登录态" },
  { id: "plugins", label: "已装插件" },
  { id: "risk", label: "风险边界" },
];

const STATE_TEXT: Record<string, { label: string; tone: string }> = {
  available: { label: "已登录", tone: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  need_login: { label: "待登录", tone: "bg-amber-50 text-amber-700 border-amber-200" },
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

const EASE = [0.22, 1, 0.36, 1] as const;

export default function SettingsPage({ ctx }: { ctx: OutletCtx }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [plugins, setPlugins] = useState<PluginsResponse | null>(null);
  const [auth, setAuth] = useState<Record<string, AuthState>>({});
  const [login, setLogin] = useState<Record<string, LoginStatus>>({});
  const [note, setNote] = useState("");
  const [form, setForm] = useState<SettingsValues | null>(null);
  const [baseline, setBaseline] = useState("");
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({ status: true, ai: true });
  const [active, setActive] = useState("status");
  const reduce = useReducedMotion();
  const copyTimer = useRef(0);

  const load = useCallback(async () => {
    try {
      const [h, p, s] = await Promise.all([
        getJSON<Health>("/api/health"),
        getJSON<PluginsResponse>("/api/plugins"),
        getJSON<SettingsResponse>("/api/settings"),
      ]);
      setHealth(h);
      setPlugins(p);
      setForm((prev) => {
        if (prev) return prev;
        setBaseline(JSON.stringify(s.settings));
        return s.settings;
      });
      const states = await Promise.all(
        ALL_AUTH_ROWS.map((id) =>
          getJSON<AuthState>("/api/auth/" + id).catch((err: Error) => ({ plugin: id, state: "error" as const, message: err.message })),
        ),
      );
      const map: Record<string, AuthState> = {};
      for (const s2 of states) map[s2.plugin] = s2;
      setAuth(map);
    } catch (err) {
      setNote((err as Error).message);
    }
  }, []);

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

  const flash = (text: string) => {
    setNote(text);
    window.clearTimeout(copyTimer.current);
    copyTimer.current = window.setTimeout(() => setNote(""), 3200);
  };

  const toggle = async (id: string, enabled: boolean) => {
    await fetch("/api/plugins/" + id, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    flash(enabled ? "已启用 " + id : "已停用 " + id);
    void load();
    ctx.bump();
  };

  const dirty = Boolean(form && baseline && JSON.stringify(form) !== baseline);

  const saveSettings = async () => {
    if (!form) return;
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
    } catch (err) {
      flash((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const clearKeys = async () => {
    await putJSON("/api/settings", { ai_api_key: "", ai_providers: [] });
    setForm((prev) => (prev ? { ...prev, ai_api_key: "", ai_providers: [] } : prev));
    setBaseline("");
    await ctx.reloadSettings();
    flash("已清除所有模型 key，AI 退回本地解析");
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
  const authReady = ALL_AUTH_ROWS.filter((id) => auth[id]?.state === "available").length;
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
      <h1 className="text-[19px] font-semibold tracking-tight">设置</h1>
      <p className="mt-1 text-[13px] text-muted">本机运行，只监听 127.0.0.1。数据、cookie、插件都在你自己的盘上。</p>

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
            <p className="px-2.5 pt-3 text-[11px] leading-relaxed text-fade">改动会在左侧「保存」条出现后一次性提交。</p>
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
                <div className="flex items-center gap-2 rounded-full border border-line bg-white px-2 py-1.5 pl-4 shadow-[0_12px_34px_rgba(20,20,20,0.16)]">
                  <span className="text-[13px] text-ink">有未保存的改动</span>
                  <button
                    onClick={() => void saveSettings()}
                    disabled={saving}
                    className="ml-auto flex h-8 items-center gap-1.5 rounded-lg bg-ink px-3 text-[13px] text-white disabled:opacity-60"
                  >
                    <Save size={12} />
                    {saving ? "保存中…" : "保存"}
                  </button>
                  <button
                    onClick={() => {
                      if (baseline) setForm(JSON.parse(baseline) as SettingsValues);
                    }}
                    className="flex h-8 items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 text-[12px] text-muted hover:text-ink"
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
            desc="版本、条目数、数据库位置"
            summary={
              <>
                <span>{health?.items ?? 0} 条</span>
                <span className="text-fade">·</span>
                <span>{health?.plugins ?? 0} 个插件</span>
                <span className="text-fade">·</span>
                <span>v{health?.version ?? "—"}</span>
              </>
            }
            open={Boolean(open.status)}
            onToggle={() => setOpen((prev) => ({ ...prev, status: !prev.status }))}
          >
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[13px]">
              <div className="flex justify-between">
                <dt className="text-fade">版本</dt>
                <dd>{health?.version ?? "—"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-fade">条目</dt>
                <dd>{health?.items ?? 0}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-fade">插件</dt>
                <dd>{health?.plugins ?? 0}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-fade">模式</dt>
                <dd>{health?.demo ? "离线演示（fixtures）" : "联网采集"}</dd>
              </div>
            </dl>
            <p className="mt-3 break-all rounded-lg bg-wash px-3 py-2 font-mono text-[12px] text-muted">{health?.db ?? "数据库路径未知"}</p>
            <div className="mt-3 flex gap-2">
              <button onClick={ctx.refresh} className="flex h-9 items-center gap-1.5 rounded-lg bg-ink px-3.5 text-[13px] text-white">
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
            desc="插件目录、每轮条数、保留天数"
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
            <p className="text-[12px] text-fade">保存后立即生效；插件目录与 registry 改动会在下一次采集时用上。</p>
            {form ? (
              <div className="mt-4 space-y-4">
                <label className="block">
                  <span className="text-[13px] font-medium">插件目录</span>
                  <input
                    value={form.plugins_dir}
                    onChange={(e) => setForm({ ...form, plugins_dir: e.target.value })}
                    placeholder={resolved?.plugins_dir ?? ""}
                    className="mt-1.5 h-9 w-full rounded-lg border border-line bg-white px-3 font-mono text-[12px] outline-none focus:border-ink/40"
                  />
                  <span className="mt-1 block text-[11px] text-fade">留空用默认目录：{resolved?.plugins_dir ?? "—"}</span>
                </label>

                <label className="block">
                  <span className="text-[13px] font-medium">插件市场 registry 地址</span>
                  <input
                    value={form.registry_url}
                    onChange={(e) => setForm({ ...form, registry_url: e.target.value })}
                    placeholder={resolved?.registry_url ?? ""}
                    className="mt-1.5 h-9 w-full rounded-lg border border-line bg-white px-3 font-mono text-[12px] outline-none focus:border-ink/40"
                  />
                  <span className="mt-1 block text-[11px] text-fade">留空用默认订阅源；换源不会读旧缓存。</span>
                </label>

                <div className="grid grid-cols-2 gap-4">
                  <label className="block">
                    <span className="text-[13px] font-medium">每平台每轮条数</span>
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={form.per_plugin_limit}
                      onChange={(e) => setForm({ ...form, per_plugin_limit: Number(e.target.value) })}
                      className="mt-1.5 h-9 w-full rounded-lg border border-line bg-white px-3 text-[13px] outline-none focus:border-ink/40"
                    />
                  </label>
                  <label className="block">
                    <span className="text-[13px] font-medium">详情页评论条数</span>
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={form.comments_limit}
                      onChange={(e) => setForm({ ...form, comments_limit: Number(e.target.value) })}
                      className="mt-1.5 h-9 w-full rounded-lg border border-line bg-white px-3 text-[13px] outline-none focus:border-ink/40"
                    />
                  </label>
                  <label className="block">
                    <span className="text-[13px] font-medium">默认排序</span>
                    <select
                      value={form.default_sort}
                      onChange={(e) => setForm({ ...form, default_sort: e.target.value })}
                      className="mt-1.5 h-9 w-full rounded-lg border border-line bg-white px-2.5 text-[13px] outline-none focus:border-ink/40"
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
                    <input
                      type="number"
                      min={1}
                      max={365}
                      value={form.prune_days}
                      onChange={(e) => setForm({ ...form, prune_days: Number(e.target.value) })}
                      className="mt-1.5 h-9 w-full rounded-lg border border-line bg-white px-3 text-[13px] outline-none focus:border-ink/40"
                    />
                  </label>
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
                      开着就每轮先查一次市场，有新版直接换上（走 sha256 校验）。现场演示建议关掉，别让远端在你讲的时候改代码。
                    </span>
                  </span>
                </label>

                <div className="flex items-center gap-2 pt-1">
                  <button
                    onClick={() => void saveSettings()}
                    disabled={saving}
                    className="flex h-9 items-center gap-1.5 rounded-lg bg-ink px-4 text-[13px] text-white disabled:opacity-60"
                  >
                    <Save size={13} />
                    {saving ? "保存中…" : "保存设置"}
                  </button>
                  <button
                    onClick={() => defaults && setForm({ ...defaults })}
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
                  {ai?.engine === "llm" ? "模型在线" : "本地解析"}
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
            <p className="text-[12px] leading-relaxed text-fade">
              模型只负责理解你的话和措辞，内容永远从本地库里取——断网也能用，只是「理解」会退回规则解析。
              排在前面的先用，超时或报错自动换下一个；每个模型的 key 只写不读，插件看不到。
            </p>
            {form ? (
              <div className="mt-4 space-y-4">
                <AiProviders
                  value={form.ai_providers ?? []}
                  onChange={(next) => setForm({ ...form, ai_providers: next })}
                  status={ai}
                />
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-fade">存本机 settings.json，接口只写不读。</span>
                  <button onClick={() => void clearKeys()} className="ml-auto h-8 rounded-lg border border-line px-3 text-[12px] text-muted hover:text-ink">
                    清除所有 key
                  </button>
                </div>
              </div>
            ) : null}
          </SettingSection>

          <SettingSection
            id="auth"
            title="登录态"
            desc="小红书、抖音、B 站"
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
            <p className="text-[12px] text-fade">插件拿不到你的明文 cookie，只由宿主在发请求时注入。登录窗口是独立的 Chrome，登录完会自动关掉。</p>
            <ul className="mt-3 space-y-2">
              {ALL_AUTH_ROWS.map((id) => {
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
                              className="flex h-7 items-center gap-1 rounded-md bg-ink px-2.5 text-[12px] text-white"
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
                    <span className="rounded-full bg-emerald-50 px-1.5 py-0.5 text-[11px] text-emerald-700">评论区</span>
                  ) : (
                    <span className="rounded-full bg-wash px-1.5 py-0.5 text-[11px] text-fade">无评论</span>
                  )}
                  <span className="text-[11px] text-fade">{p.source === "registry" ? "市场安装" : "本地"}</span>
                  <button
                    onClick={() => void toggle(p.id, !p.enabled)}
                    className={"ml-auto h-6 w-11 rounded-full p-0.5 transition " + (p.enabled ? "bg-ink" : "bg-line")}
                    title={p.enabled ? "点击停用" : "点击启用"}
                  >
                    <span className={"block h-5 w-5 rounded-full bg-white shadow transition-transform duration-200 " + (p.enabled ? "translate-x-5" : "translate-x-0")} />
                  </button>
                </li>
              ))}
              {!installed.length ? <li className="py-3 text-[13px] text-muted">还没装插件，去市场挑两个。</li> : null}
            </ul>
            {plugins?.errors?.length ? <p className="mt-2 text-[12px] text-amber-600">有插件加载失败：{plugins.errors.join("；")}</p> : null}
          </SettingSection>

          <SettingSection
            id="risk"
            title="风险边界"
            desc="只读、沙箱、凭证不出宿主"
            open={Boolean(open.risk)}
            onToggle={() => setOpen((prev) => ({ ...prev, risk: !prev.risk }))}
          >
            <ul className="mt-1 space-y-1.5 text-[13px] leading-relaxed text-muted">
              <li className="flex items-start gap-1.5">
                <ShieldCheck size={14} className="mt-0.5 shrink-0 text-muted" />
                只读：不下载、不转发、不代发内容，只把公开页面上看得到的东西排好给你。
              </li>
              <li>插件跑在 QuickJS 子进程里，每个插件独立进程，超时直接强杀。</li>
              <li>不内置任何密钥；登录态只存在本机，插件只能通过宿主能力发请求。</li>
              <li>装第三方插件前先看一眼它的 index.js —— 它能看到的东西和你浏览器里一样多。</li>
            </ul>
          </SettingSection>
        </div>
      </div>

      <AnimatePresence>
        {note ? (
          <motion.div
            key="note"
            initial={{ opacity: 0, y: 10, scale: 0.98, x: "-50%" }}
            animate={{ opacity: 1, y: 0, scale: 1, x: "-50%" }}
            exit={{ opacity: 0, y: 10, scale: 0.98, x: "-50%" }}
            transition={{ duration: reduce ? 0 : 0.2, ease: EASE }}
            className="fixed bottom-6 left-1/2 z-50 rounded-full bg-ink px-5 py-2.5 text-[13px] text-white shadow-pop"
          >
            {note}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
