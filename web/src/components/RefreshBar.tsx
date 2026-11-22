import { useEffect, useMemo, useState } from "react";
import { AlertCircle, Check, Loader2, RotateCw, X } from "lucide-react";
import type { RunState } from "../api";

interface Props {
  progress: RunState | null;
  /** 这一轮是否已经演过清场登场：演过就不再给「看新内容」入口 */
  played?: boolean;
  onRetry: (platforms: string[]) => void;
  onNew: () => void;
}

/**
 * 刷新时的一行内联状态条：进行中给到平台粒度，结束后原地换成结果与处置。
 *
 * 高度恒定 40px（没有运行时也占位），任何状态切换都不会把下面的正文推上推下。
 * 失败详情走 toast（带「只重试这个平台」），不在行内展开——展开会改变高度，
 * 而这条状态条存在的意义之一就是「高度不许变」。
 */
export default function RefreshBar({ progress, played, onRetry, onNew }: Props) {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  const [dismissed, setDismissed] = useState(() => {
    const raw = Number(window.localStorage.getItem("onefeed:refresh-dismissed") || 0);
    return Number.isFinite(raw) ? raw : 0;
  });
  const running = Boolean(progress?.running);
  const phase = String(progress?.phase || (running ? "fetching" : "idle"));
  const settling = phase === "settling";

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => window.clearInterval(timer);
  }, [running]);

  const rows = useMemo(
    () =>
      Object.entries(progress?.plugins ?? {}).map(([id, p]) => ({
        id,
        label: p.label || id,
        status: p.status,
        count: Number(p.count || 0),
        fresh: Number(p.new_count || 0),
        error: p.error || "",
      })),
    [progress],
  );

  const failed = rows.filter((row) => row.status === "failed");
  const cooling = rows.filter((row) => row.status === "skipped");
  const newTotal = Number(progress?.new_total ?? 0);
  const started = Number(progress?.started_at ?? 0);
  const elapsed = started ? Math.max(0, now - started) : 0;
  const idle = !progress || (!running && !progress.finished_at);
  const hidden = dismissed > 0 && dismissed === started;

  // 没有运行、也没有刚结束的一轮：保留 40px 占位，别让正文上下跳
  if (idle || hidden) return <div className="mt-4 h-10" aria-hidden="true" />;

  const dismiss = () => {
    setDismissed(started);
    window.localStorage.setItem("onefeed:refresh-dismissed", String(started));
  };

  const explain = (row: (typeof rows)[number]) => {
    window.dispatchEvent(
      new CustomEvent("onefeed:toast", {
        detail: {
          text: (row.label + "：" + (row.error || "没抓到")).slice(0, 140),
          action: { label: "只重试它", run: () => onRetry([row.id]) },
        },
      }),
    );
  };

  const headline = running
    ? "正在抓取 " + Number(progress?.done || 0) + "/" + Number(progress?.total || 0)
    : settling
      ? "整理中"
      : "这一轮 +" + newTotal + " 条";

  const tail = running ? "已 " + elapsed + "s" : settling ? "马上好" : "";

  return (
    <section
      data-refresh-bar="1"
      aria-live="polite"
      aria-busy={running || settling}
      className="mt-4 flex h-10 items-center gap-2 overflow-hidden rounded-[10px] border border-line bg-wash/60 px-2.5 text-[12px]"
    >
      <span className="shrink-0 font-medium tabular-nums text-ink">{headline}</span>

      <span className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {rows.map((row, index) => {
          const extra = index >= 3 ? "hidden sm:inline-flex" : "inline-flex";
          if (row.status === "running") {
            return (
              <span key={row.id} className={extra + " shrink-0 items-center gap-1 text-ink"}>
                <Loader2 size={11} className="animate-spin text-accent" />
                {row.label}
              </span>
            );
          }
          if (row.status === "ok") {
            return (
              <span key={row.id} className={extra + " shrink-0 items-center gap-1 text-muted"}>
                <Check size={11} className="text-accent" />
                {row.label} {row.fresh > 0 ? "+" + row.fresh : row.count}
              </span>
            );
          }
          if (row.status === "failed") {
            return (
              <button
                key={row.id}
                type="button"
                onClick={() => explain(row)}
                title={(row.error || "没抓到").slice(0, 140)}
                className={extra + " shrink-0 items-center gap-1 text-danger"}
              >
                <AlertCircle size={11} />
                {row.label}
              </button>
            );
          }
          if (row.status === "skipped") {
            return (
              <span key={row.id} className={extra + " shrink-0 items-center gap-1 text-fade"}>
                <span className="h-1.5 w-1.5 rounded-full bg-fade" />
                {row.label}
              </span>
            );
          }
          return (
            <span key={row.id} className={extra + " shrink-0 items-center gap-1 text-fade"}>
              <span className="h-1.5 w-1.5 rounded-full bg-line" />
              {row.label}
            </span>
          );
        })}
        {rows.length > 3 ? (
          <span className="shrink-0 text-fade sm:hidden">+{rows.length - 3}</span>
        ) : null}
      </span>

      {tail ? <span className="shrink-0 text-fade tabular-nums">{tail}</span> : null}

      {!running && !settling ? (
        <span className="flex shrink-0 items-center gap-1">
          {cooling.length ? (
            <span className="hidden text-fade sm:inline">{cooling.length} 个冷却</span>
          ) : null}
          {failed.length ? (
            <button
              type="button"
              onClick={() => onRetry(failed.map((row) => row.id))}
              className="inline-flex h-6 items-center gap-1 rounded-full px-1.5 text-muted transition hover:bg-paper hover:text-ink"
            >
              <RotateCw size={11} />
              重试失败
            </button>
          ) : null}
          {newTotal > 0 && !played ? (
            <button
              type="button"
              onClick={onNew}
              className="inline-flex h-6 items-center rounded-full bg-ink px-2 text-[11px] text-paper"
            >
              看新内容
            </button>
          ) : newTotal > 0 ? (
            <span className="hidden text-fade sm:inline">刚放进来的 {newTotal} 条</span>
          ) : null}
          <button
            type="button"
            onClick={dismiss}
            aria-label="收起这一轮的进度"
            title="收起"
            className="inline-flex h-6 w-6 items-center justify-center rounded-full text-fade transition hover:bg-paper hover:text-ink"
          >
            <X size={12} />
          </button>
        </span>
      ) : null}
    </section>
  );
}
