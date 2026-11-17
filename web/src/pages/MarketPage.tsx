import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpCircle, Check, Download, RefreshCw, Trash2 } from "lucide-react";
import type { OutletCtx } from "../App";
import { deleteJSON, getJSON, postJSON, type MarketEntry, type PluginsResponse } from "../api";
import { KIND_LABEL } from "../platform";

interface UpdateResult {
  from?: string;
  to?: string;
  changed?: boolean;
  id?: string;
}

export default function MarketPage({ ctx }: { ctx: OutletCtx }) {
  const [data, setData] = useState<PluginsResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [note, setNote] = useState("");
  const [reload, setReload] = useState(0);

  const load = useCallback(async (force = false) => {
    setError("");
    try {
      const resp = await getJSON<PluginsResponse>("/api/plugins?refresh_market=" + String(force));
      setData(resp);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, reload, ctx.reloadKey]);

  const flash = (text: string) => {
    setNote(text);
    window.setTimeout(() => setNote(""), 3600);
  };

  const install = async (id: string) => {
    setBusy(id);
    try {
      await postJSON("/api/plugins/" + id + "/install");
      flash("装好了：" + id + "，刷新一轮就有新来源");
      setReload((n) => n + 1);
      ctx.bump();
    } catch (err) {
      flash((err as Error).message);
    } finally {
      setBusy("");
    }
  };

  const update = async (entry: MarketEntry) => {
    setBusy(entry.id);
    try {
      const resp = await postJSON<{ result: UpdateResult }>("/api/plugins/" + entry.id + "/update");
      const r = resp.result ?? {};
      flash(r.changed === false ? entry.id + " 已经是最新版" : entry.id + " 升到 v" + (r.to ?? "?"));
      setReload((n) => n + 1);
    } catch (err) {
      flash((err as Error).message);
    } finally {
      setBusy("");
    }
  };

  const updateAll = async () => {
    setBusy("__all__");
    try {
      const resp = await postJSON<{
        result: { updated: UpdateResult[]; failed: { id: string; error: string }[]; pending: number };
      }>("/api/market/update-all");
      const r = resp.result ?? { updated: [], failed: [], pending: 0 };
      const done = r.updated.length;
      const bad = r.failed.length;
      flash(
        done || bad
          ? "更新 " + done + " 个" + (bad ? "，" + bad + " 个失败（" + r.failed[0].id + "）" : "")
          : "没有可更新的插件",
      );
      setReload((n) => n + 1);
    } catch (err) {
      flash((err as Error).message);
    } finally {
      setBusy("");
    }
  };

  const remove = async (id: string) => {
    setBusy(id);
    try {
      await deleteJSON("/api/plugins/" + id);
      flash("已卸载：" + id);
      setReload((n) => n + 1);
      ctx.bump();
    } catch (err) {
      flash((err as Error).message);
    } finally {
      setBusy("");
    }
  };

  const entries: MarketEntry[] = data?.market.entries ?? [];
  const pending = useMemo(() => entries.filter((e) => e.update_available && e.installed), [entries]);

  return (
    <div className="pb-24 pt-6">
      <div className="flex items-end gap-3">
        <div>
          <h1 className="text-[19px] font-semibold tracking-tight">插件市场</h1>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {pending.length ? (
            <button
              onClick={() => void updateAll()}
              disabled={busy === "__all__"}
              className="flex h-9 items-center gap-1.5 rounded-full bg-solid px-3.5 text-[13px] text-solid-fg disabled:opacity-50"
            >
              <ArrowUpCircle size={14} />
              {busy === "__all__" ? "更新中…" : "全部更新 (" + pending.length + ")"}
            </button>
          ) : null}
          <button
            onClick={() => {
              void load(true);
              setReload((n) => n + 1);
            }}
            className="flex h-9 items-center gap-1.5 rounded-full border border-line px-3.5 text-[13px] text-muted hover:border-ink/25 hover:text-ink"
          >
            <RefreshCw size={14} />
            刷新目录
          </button>
        </div>
      </div>

      {data?.market.degraded ? (
        <div className="mt-4 rounded-card border border-amber-200 dark:border-amber-500/30 bg-amber-50 dark:bg-amber-500/10 px-4 py-3 text-[13px] text-amber-800 dark:text-amber-200">
          市场降级：{data.market.degraded}
        </div>
      ) : null}

      {error ? (
        <div className="mt-4 rounded-card border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700">{error}</div>
      ) : null}

      {!data && !error ? (
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-[148px] skeleton rounded-card border border-line" />
          ))}
        </div>
      ) : null}

      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        {entries.map((entry, index) => (
          <article
            key={entry.id}
            className="rise rounded-card border border-line p-5"
            style={{ animationDelay: Math.min(index, 9) * 28 + "ms" }}
          >
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-[15px] font-semibold">{entry.name || entry.id}</h2>
                  <span className="text-[11px] text-fade">
                    {entry.installed && entry.installed_version && entry.update_available
                      ? "v" + entry.installed_version + " → v" + (entry.latest_version || entry.version)
                      : "v" + entry.version}
                  </span>
                  {entry.update_available ? (
                    <span className="rounded-full bg-solid px-1.5 py-0.5 text-[11px] text-solid-fg">可更新</span>
                  ) : null}
                  {entry.installed ? (
                    <span className="flex items-center gap-0.5 rounded-full border border-line px-1.5 py-0.5 text-[11px] text-muted">
                      <Check size={10} />
                      已安装{entry.enabled ? "" : " · 已停用"}
                    </span>
                  ) : null}
                </div>
                <p className="clamp-2 mt-1.5 text-[13px] leading-relaxed text-muted">{entry.description}</p>
              </div>
              <div className="flex shrink-0 flex-col items-end gap-1.5">
                {entry.installed && entry.update_available ? (
                  <button
                    onClick={() => void update(entry)}
                    disabled={busy === entry.id}
                    className="flex h-8 items-center gap-1 rounded-lg bg-solid px-3 text-[12px] text-solid-fg disabled:opacity-50"
                  >
                    <ArrowUpCircle size={13} />
                    {busy === entry.id ? "更新中" : "更新"}
                  </button>
                ) : null}
                {entry.installed ? (
                  <button
                    onClick={() => void remove(entry.id)}
                    disabled={busy === entry.id}
                    className="flex h-8 items-center gap-1 rounded-lg border border-line px-2.5 text-[12px] text-muted hover:border-red-200 hover:text-red-600 disabled:opacity-50"
                  >
                    <Trash2 size={13} />
                    卸载
                  </button>
                ) : (
                  <button
                    onClick={() => void install(entry.id)}
                    disabled={busy === entry.id}
                    className="flex h-8 items-center gap-1 rounded-lg bg-solid px-3 text-[12px] text-solid-fg disabled:opacity-50"
                  >
                    <Download size={13} />
                    {busy === entry.id ? "安装中" : "安装"}
                  </button>
                )}
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {entry.kinds.map((k) => (
                <span key={k} className="rounded-full bg-wash px-2 py-0.5 text-[11px] text-muted">
                  {KIND_LABEL[k] ?? k}
                </span>
              ))}
              {entry.features?.includes("comments") ? (
                <span className="rounded-full border border-line px-2 py-0.5 text-[11px] text-fade">评论区</span>
              ) : null}
              {entry.capabilities.map((c) => (
                <span key={c} className="rounded-full border border-line px-2 py-0.5 text-[11px] text-fade">
                  {c}
                </span>
              ))}
            </div>
          </article>
        ))}
      </div>

      {data && !entries.length && !error ? (
        <div className="mt-16 text-center text-[13px] text-muted">目录是空的，点右上角「刷新目录」再试一次。</div>
      ) : null}

      <p className="mt-8 text-[12px] text-fade">
        目录：{data?.market.url ?? "registry.json"}
        {data?.market.from_cache ? "（本地缓存）" : ""}
      </p>

      {note ? (
        <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full bg-solid px-5 py-2.5 text-[13px] text-solid-fg shadow-pop">
          {note}
        </div>
      ) : null}
    </div>
  );
}
