import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, Check, RefreshCw, ShieldCheck } from "lucide-react";
import type { OutletCtx } from "../App";
import { getJSON, type AuthState, type Health, type PluginsResponse } from "../api";
import { platform } from "../platform";

const AUTH_PLUGINS = ["xiaohongshu", "douyin"];

const STATE_TEXT: Record<string, { label: string; tone: string }> = {
  available: { label: "已登录", tone: "bg-emerald-50 text-emerald-700 border-emerald-200" },
  need_login: { label: "待登录", tone: "bg-amber-50 text-amber-700 border-amber-200" },
  error: { label: "读取失败", tone: "bg-red-50 text-red-700 border-red-200" },
  not_required: { label: "无需登录", tone: "bg-wash text-muted border-line" },
};

export default function SettingsPage({ ctx }: { ctx: OutletCtx }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [plugins, setPlugins] = useState<PluginsResponse | null>(null);
  const [auth, setAuth] = useState<Record<string, AuthState>>({});
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    try {
      const [h, p] = await Promise.all([getJSON<Health>("/api/health"), getJSON<PluginsResponse>("/api/plugins")]);
      setHealth(h);
      setPlugins(p);
      const states = await Promise.all(
        AUTH_PLUGINS.map((id) => getJSON<AuthState>("/api/auth/" + id).catch((err: Error) => ({ plugin: id, state: "error" as const, message: err.message }))),
      );
      const map: Record<string, AuthState> = {};
      for (const s of states) map[s.plugin] = s;
      setAuth(map);
    } catch (err) {
      setNote((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, ctx.reloadKey]);

  const toggle = async (id: string, enabled: boolean) => {
    await fetch("/api/plugins/" + id, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    setNote(enabled ? "已启用 " + id : "已停用 " + id);
    window.setTimeout(() => setNote(""), 2600);
    void load();
  };

  return (
    <div className="max-w-[820px] pb-24 pt-6">
      <h1 className="text-[19px] font-semibold tracking-tight">设置</h1>
      <p className="mt-1 text-[13px] text-muted">本机运行，只监听 127.0.0.1。数据、cookie、插件都在你自己的盘上。</p>

      <section className="mt-6 rounded-card border border-line p-5">
        <h2 className="text-[14px] font-semibold">运行状态</h2>
        <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 text-[12.5px]">
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
        <p className="mt-3 break-all rounded-lg bg-wash px-3 py-2 font-mono text-[11.5px] text-muted">
          {health?.db ?? "数据库路径未知"}
        </p>
        <div className="mt-3 flex gap-2">
          <button
            onClick={ctx.refresh}
            className="flex h-9 items-center gap-1.5 rounded-lg bg-ink px-3.5 text-[12.5px] text-white"
          >
            <RefreshCw size={13} />
            现在刷新一轮
          </button>
          <button onClick={() => void load()} className="h-9 rounded-lg border border-line px-3.5 text-[12.5px] text-muted hover:text-ink">
            重新检查
          </button>
        </div>
      </section>

      <section className="mt-5 rounded-card border border-line p-5">
        <h2 className="text-[14px] font-semibold">登录态</h2>
        <p className="mt-1 text-[12px] text-fade">
          插件拿不到你的 cookie，只能通过宿主发请求。cookie 文件放在状态目录 cookies/ 下。
        </p>
        <ul className="mt-3 space-y-2">
          {AUTH_PLUGINS.map((id) => {
            const state = auth[id];
            const meta = STATE_TEXT[state?.state ?? "need_login"] ?? STATE_TEXT.need_login;
            return (
              <li key={id} className="flex items-start gap-3 rounded-lg border border-line px-3.5 py-3">
                <span className="mt-1.5 h-[7px] w-[7px] rounded-full" style={{ background: platform(id).tint }} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 text-[13px] font-medium">
                    {platform(id).label}
                    <span className={"rounded-full border px-1.5 py-0.5 text-[10px] " + meta.tone}>{meta.label}</span>
                  </div>
                  <p className="mt-1 text-[12px] leading-relaxed text-muted">
                    {state?.message || "还没检查"}
                    {state?.hint ? " · " + state.hint : ""}
                  </p>
                </div>
                {state?.state === "available" ? <Check size={15} className="mt-1 text-emerald-600" /> : <AlertTriangle size={15} className="mt-1 text-amber-500" />}
              </li>
            );
          })}
        </ul>
      </section>

      <section className="mt-5 rounded-card border border-line p-5">
        <h2 className="text-[14px] font-semibold">已装插件</h2>
        <ul className="mt-3 divide-y divide-line">
          {(plugins?.installed ?? []).map((p) => (
            <li key={p.id} className="flex items-center gap-3 py-2.5">
              <span className="h-[7px] w-[7px] rounded-full" style={{ background: platform(p.id).tint }} />
              <span className="text-[13px]">{platform(p.id).label}</span>
              <span className="text-[11px] text-fade">v{p.version}</span>
              <span className="text-[11px] text-fade">{p.source === "registry" ? "市场安装" : "本地"}</span>
              <button
                onClick={() => void toggle(p.id, !p.enabled)}
                className={
                  "ml-auto h-6 w-11 rounded-full p-0.5 transition " + (p.enabled ? "bg-ink" : "bg-line")
                }
                title={p.enabled ? "点击停用" : "点击启用"}
              >
                <span
                  className={
                    "block h-5 w-5 rounded-full bg-white shadow transition " + (p.enabled ? "translate-x-5" : "translate-x-0")
                  }
                />
              </button>
            </li>
          ))}
          {!(plugins?.installed ?? []).length ? (
            <li className="py-3 text-[12.5px] text-muted">还没装插件，去市场挑两个。</li>
          ) : null}
        </ul>
      </section>

      <section className="mt-5 rounded-card border border-line p-5">
        <h2 className="flex items-center gap-1.5 text-[14px] font-semibold">
          <ShieldCheck size={15} className="text-muted" />
          风险边界
        </h2>
        <ul className="mt-2 space-y-1.5 text-[12.5px] leading-relaxed text-muted">
          <li>只读：不下载、不转发、不代发内容，只把公开页面上看得到的东西排好给你。</li>
          <li>插件跑在 QuickJS 子进程里，每个插件独立进程，超时直接强杀。</li>
          <li>不内置任何密钥；登录态只存在本机，插件只能通过宿主能力发请求。</li>
          <li>装第三方插件前先看一眼它的 index.js —— 它能看到的东西和你浏览器里一样多。</li>
        </ul>
      </section>

      {note ? (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full bg-ink px-5 py-2.5 text-[13px] text-white shadow-pop">
          {note}
        </div>
      ) : null}
    </div>
  );
}
