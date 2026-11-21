import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowUpCircle, Check, Download, RefreshCw, Trash2 } from "lucide-react";
import type { OutletCtx } from "../App";
import { deleteJSON, getJSON, postJSON, type MarketEntry, type PluginsResponse } from "../api";
import { KIND_LABEL } from "../platform";
import { useBatchAction } from "../motion/useAction";
import { confirmDialog } from "../components/ui/Confirm";

interface UpdateResult {
  from?: string;
  to?: string;
  changed?: boolean;
  id?: string;
}

export default function MarketPage({ ctx }: { ctx: OutletCtx }) {
  useEffect(() => {
    document.title = "插件市场 · OneFeed";
  }, []);
  const [data, setData] = useState<PluginsResponse | null>(null);
  const [error, setError] = useState("");
  // 每个插件各管各的 pending：以前共用一个 busy 字符串，同时装两个会互相覆盖 spinner
  const batch = useBatchAction<string>();
  const [note, setNote] = useState("");
  const [reload, setReload] = useState(0);
  // 卸载后留 5 秒反悔：卸载是把本机插件目录删掉，误点一次得能一键装回来
  const [undo, setUndo] = useState("");
  const noteTimer = useRef<number | undefined>(undefined);
  const undoTimer = useRef<number | undefined>(undefined);

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
    // 旧定时器必须清掉，否则连续操作时前一条的计时会提前抹掉后一条提示
    if (noteTimer.current) window.clearTimeout(noteTimer.current);
    noteTimer.current = window.setTimeout(() => setNote(""), 3600);
  };

  const armUndo = (id: string) => {
    setUndo(id);
    if (undoTimer.current) window.clearTimeout(undoTimer.current);
    undoTimer.current = window.setTimeout(() => setUndo(""), 5000);
  };
  const clearUndo = () => {
    if (undoTimer.current) window.clearTimeout(undoTimer.current);
    setUndo("");
  };

  useEffect(() => () => {
    if (noteTimer.current) window.clearTimeout(noteTimer.current);
    if (undoTimer.current) window.clearTimeout(undoTimer.current);
  }, []);

  const install = async (id: string) => {
    const res = await batch.run(id, async () => {
      await postJSON("/api/plugins/" + id + "/install");
      flash("装好了：" + id + "，刷新一轮就有新来源");
      setReload((n) => n + 1);
      ctx.bump();
    });
    if (!res.ok) flash(res.error);
  };

  const update = async (entry: MarketEntry) => {
    const res = await batch.run(entry.id, async () => {
      const resp = await postJSON<{ result: UpdateResult }>("/api/plugins/" + entry.id + "/update");
      const r = resp.result ?? {};
      flash(r.changed === false ? entry.id + " 已经是最新版" : entry.id + " 升到 v" + (r.to ?? "?"));
      setReload((n) => n + 1);
    });
    if (!res.ok) flash(res.error);
  };

  const updateAll = async () => {
    const res = await batch.run("__all__", async () => {
      const resp = await postJSON<{
        result: { updated: UpdateResult[]; failed: { id: string; error: string }[]; pending: number };
      }>("/api/market/update-all");
      const r = resp.result ?? { updated: [], failed: [], pending: 0 };
      const done = r.updated.length;
      const bad = r.failed.length;
      // 失败不止一个时把名字列出来，只报第一个等于让用户去猜
      const names = r.failed
        .slice(0, 3)
        .map((f) => f.id)
        .join("、");
      flash(
        done || bad
          ? "更新 " + done + " 个" + (bad ? "，" + bad + " 个失败（" + names + (bad > 3 ? " 等" : "") + "）" : "")
          : "没有可更新的插件",
      );
      setReload((n) => n + 1);
    });
    if (!res.ok) flash(res.error);
  };

  const remove = async (id: string) => {
    const ok = await confirmDialog({
      title: "卸载 " + id + "？",
      body: "会删掉本机这个插件的目录，之后要重新从市场安装，这个来源的历史条目会留在库里但无法再刷新。",
      confirmText: "卸载",
      tone: "danger",
    });
    if (!ok) return;
    const res = await batch.run(id, async () => {
      await deleteJSON("/api/plugins/" + id);
      flash("已卸载：" + id);
      armUndo(id);
      setReload((n) => n + 1);
      ctx.bump();
    });
    if (!res.ok) flash(res.error);
  };

  const entries: MarketEntry[] = data?.market.entries ?? [];
  const pending = useMemo(() => entries.filter((e) => e.update_available && e.installed), [entries]);

  return (
    <div className="pb-24 pt-6">
      <div className="flex items-end gap-3">
        <div>
          <h1 className="font-display text-[19px] font-semibold tracking-tight">插件市场</h1>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {pending.length ? (
            <button
              onClick={() => void updateAll()}
              disabled={batch.has("__all__")}
              className="flex h-9 items-center gap-1.5 rounded-full bg-solid px-3.5 text-[13px] text-solid-fg disabled:opacity-50"
            >
              <ArrowUpCircle size={14} />
              {batch.has("__all__") ? "更新中…" : "全部更新 (" + pending.length + ")"}
            </button>
          ) : null}
          <button
            onClick={() => void load(true)}
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
            data-plugin-id={entry.id}
            className="rise rounded-card border border-line p-5"
            style={{ animationDelay: Math.min(index, 9) * 28 + "ms" }}
          >
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="font-display text-[15px] font-semibold">{entry.name || entry.id}</h2>
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
                    disabled={batch.has(entry.id)}
                    className="flex h-8 items-center gap-1 rounded-lg bg-solid px-3 text-[12px] text-solid-fg disabled:opacity-50"
                  >
                    <ArrowUpCircle size={13} />
                    {batch.has(entry.id) ? "更新中" : "更新"}
                  </button>
                ) : null}
                {entry.installed ? (
                  <button
                    onClick={() => void remove(entry.id)}
                    disabled={batch.has(entry.id)}
                    className="flex h-8 items-center gap-1 rounded-lg border border-line px-2.5 text-[12px] text-muted hover:border-danger/40 hover:text-danger disabled:opacity-50"
                  >
                    <Trash2 size={13} />
                    卸载
                  </button>
                ) : (
                  <button
                    onClick={() => void install(entry.id)}
                    disabled={batch.has(entry.id)}
                    className="flex h-8 items-center gap-1 rounded-lg bg-solid px-3 text-[12px] text-solid-fg disabled:opacity-50"
                  >
                    <Download size={13} />
                    {batch.has(entry.id) ? "安装中" : "安装"}
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

      {note || undo ? (
        <div className="rise fixed bottom-6 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full bg-solid px-5 py-2.5 text-[13px] text-solid-fg shadow-pop">
          <span>{note || "已卸载：" + undo}</span>
          {undo ? (
            <button
              onClick={() => {
                const id = undo;
                clearUndo();
                void install(id);
              }}
              className="rounded-full bg-solid-fg/15 px-2.5 py-0.5 text-[12px] hover:bg-solid-fg/25"
            >
              撤销
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
