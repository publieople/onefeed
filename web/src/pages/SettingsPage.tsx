import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Copy, ExternalLink, LogIn, LogOut, RefreshCw, Save, ShieldCheck } from "lucide-react";
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

const AUTH_PLUGINS = ["xiaohongshu", "douyin"];
const ALL_AUTH_ROWS = [...AUTH_PLUGINS, "bilibili"];

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

export default function SettingsPage({ ctx }: { ctx: OutletCtx }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [plugins, setPlugins] = useState<PluginsResponse | null>(null);
  const [auth, setAuth] = useState<Record<string, AuthState>>({});
  const [login, setLogin] = useState<Record<string, LoginStatus>>({});
  const [note, setNote] = useState("");
  const [form, setForm] = useState<SettingsValues | null>(null);
  const [saving, setSaving] = useState(false);
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
      setForm((prev) => prev ?? s.settings);
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

  const saveSettings = async () => {
    if (!form) return;
    setSaving(true);
    try {
      const resp = await putJSON<{ ok: boolean; settings: SettingsValues; applied: string[]; resolved: SettingsResponse["resolved"] }>(
        "/api/settings",
        form,
      );
      setForm(resp.settings);
      await ctx.reloadSettings();
      flash(resp.applied?.length ? "已保存：" + resp.applied.join("；") : "已保存");
      void load();
    } catch (err) {
      flash((err as Error).message);
    } finally {
      setSaving(false);
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

  return (
    <div className="max-w-[860px] pb-24 pt-6">
      <h1 className="text-[19px] font-semibold tracking-tight">设置</h1>
      <p className="mt-1 text-[13px] text-muted">本机运行，只监听 127.0.0.1。数据、cookie、插件都在你自己的盘上。</p>

      <section className="mt-6 rounded-card border border-line p-5">
        <h2 className="text-[15px] font-semibold">运行状态</h2>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-[13px]">
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
      </section>

      <section className="mt-5 rounded-card border border-line p-5">
        <h2 className="text-[15px] font-semibold">采集与排序</h2>
        <p className="mt-1 text-[12px] text-fade">保存后立即生效；插件目录与 registry 改动会在下一次采集时用上。</p>
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
              <span className="ml-auto text-[11px] text-fade">状态目录：{resolved?.state_dir ?? "—"}</span>
            </div>
          </div>
        ) : (
          <div className="mt-3 min-h-[420px] animate-pulse space-y-3">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-9 rounded-lg bg-wash" />
            ))}
          </div>
        )}
      </section>

      <section className="mt-5 rounded-card border border-line p-5">
        <h2 className="text-[15px] font-semibold">登录态</h2>
        <p className="mt-1 text-[12px] text-fade">插件拿不到你的明文 cookie，只由宿主在发请求时注入。登录窗口是独立的 Chrome，登录完会自动关掉。</p>
        <ul className="mt-3 space-y-2">
          {ALL_AUTH_ROWS.map((id) => {
            const state = auth[id];
            const meta = STATE_TEXT[state?.state ?? "need_login"] ?? STATE_TEXT.need_login;
            const pending = login[id]?.state === "opened" || login[id]?.state === "waiting";
            const isCli = Boolean(state?.cli);
            return (
              <li key={id} className="rounded-lg border border-line px-3.5 py-3">
                <div className="flex items-center gap-2 flex-wrap">
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
                {state?.hint && !login[id] ? <p className="mt-1 text-[12px] text-fade">{state.hint}</p> : null}
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
      </section>

      <section className="mt-5 rounded-card border border-line p-5">
        <h2 className="text-[15px] font-semibold">已装插件</h2>
        <ul className="mt-3 divide-y divide-line">
          {(plugins?.installed ?? []).map((p) => (
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
                <span className={"block h-5 w-5 rounded-full bg-white shadow transition " + (p.enabled ? "translate-x-5" : "translate-x-0")} />
              </button>
            </li>
          ))}
          {!(plugins?.installed ?? []).length ? <li className="py-3 text-[13px] text-muted">还没装插件，去市场挑两个。</li> : null}
        </ul>
        {plugins?.errors?.length ? (
          <p className="mt-2 text-[12px] text-amber-600">有插件加载失败：{plugins.errors.join("；")}</p>
        ) : null}
      </section>

      <section className="mt-5 rounded-card border border-line p-5">
        <h2 className="flex items-center gap-1.5 text-[15px] font-semibold">
          <ShieldCheck size={15} className="text-muted" />
          风险边界
        </h2>
        <ul className="mt-2 space-y-1.5 text-[13px] leading-relaxed text-muted">
          <li>只读：不下载、不转发、不代发内容，只把公开页面上看得到的东西排好给你。</li>
          <li>插件跑在 QuickJS 子进程里，每个插件独立进程，超时直接强杀。</li>
          <li>不内置任何密钥；登录态只存在本机，插件只能通过宿主能力发请求。</li>
          <li>装第三方插件前先看一眼它的 index.js —— 它能看到的东西和你浏览器里一样多。</li>
        </ul>
      </section>

      {note ? (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full bg-ink px-5 py-2.5 text-[13px] text-white shadow-pop">{note}</div>
      ) : null}
    </div>
  );
}