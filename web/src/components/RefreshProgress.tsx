import { useEffect, useMemo, useRef, useState } from "react";
import { AlertCircle, Loader2, X } from "lucide-react";
import type { RunState } from "../api";

/** 结束后还留多久：够看清「+N 条」，又不至于一直挂在顶栏上。 */
const LINGER_MS = 6000;
const DISMISS_KEY = "onefeed:refresh-dismissed";

/**
 * 刷新进度：从刷新按钮左侧长出来的一枚小胶囊，收起后宽度归零、不留位。
 *
 * 以前的进度条占信息流整行，没有运行时还要占 40px 空位；顶栏那条 2px 线又是另一份进度。
 * 现在合成一件：贴着刷新按钮，长出来是进度，停 6 秒是结果，然后缩回去。
 * 绝对定位 + 量宽后补间宽度，所以长出和收起都不推动任何东西。
 */
export default function RefreshProgress({
  progress,
  hint,
  onRetry,
}: {
  progress: RunState | null;
  /** 每变一次就把卡片重新亮出来（运行中再点刷新 → 告诉人「我看到你了」） */
  hint: number;
  onRetry: (platforms: string[]) => void;
}) {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  const [dismissed, setDismissed] = useState(() => {
    try {
      return Number(window.localStorage.getItem(DISMISS_KEY) || 0) || 0;
    } catch {
      // 隐私模式下 localStorage 会抛，进度件照常工作
      return 0;
    }
  });
  // 已经自动收起的轮次（按 finished_at 认）
  const [lingered, setLingered] = useState(0);
  const [hover, setHover] = useState(false);
  const [flash, setFlash] = useState(false);

  const running = Boolean(progress?.running);
  const phase = progress?.phase ?? (running ? "fetching" : "idle");
  const settling = phase === "settling";
  const live = running || settling;
  const started = Number(progress?.started_at ?? 0);
  const finishedAt = Number(progress?.finished_at ?? 0);
  const done = progress?.done ?? 0;
  const total = progress?.total ?? 0;
  const newTotal = Number(progress?.new_total ?? 0);
  const elapsed = started ? Math.max(0, now - started) : 0;

  const rows = useMemo(
    () =>
      Object.entries(progress?.plugins ?? {}).map(([id, p]) => ({
        id,
        label: p.label || id,
        status: p.status,
        error: p.error,
      })),
    [progress],
  );
  const failed = rows.filter((r) => r.status === "failed");
  const runningLabel = rows.find((r) => r.status === "running")?.label ?? "";

  const show =
    Boolean(progress) &&
    !(dismissed > 0 && dismissed === started) &&
    (live || (finishedAt > 0 && lingered !== finishedAt));

  // 宽度靠量出来的实际尺寸补间。grid-cols-[0fr]/[1fr] 那套在绝对定位的容器里
  // 会把 1fr 算成 min-content（实测只剩 18px，内容全被裁掉），所以不用它。
  const inner = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = inner.current;
    if (!el) return;
    const measure = () => setWidth(el.offsetWidth);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // 填充只在进行中画：结束后胶囊是「结果」，再留一条满格底色像被选中了
  const fill = live ? (total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 8) : 0;

  useEffect(() => {
    if (!running) return;
    const t = window.setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => window.clearInterval(t);
  }, [running]);

  useEffect(() => {
    if (!finishedAt || live || hover) return;
    if (lingered === finishedAt) return;
    const t = window.setTimeout(() => setLingered(finishedAt), LINGER_MS);
    return () => window.clearTimeout(t);
  }, [finishedAt, live, hover, lingered]);

  // 运行中点了刷新 / 收起过又来了新的一轮：重新展开并闪一下，
  // 否则按钮在转圈而进度件缩着，看起来就是「点了没反应」
  useEffect(() => {
    if (!hint) return;
    setDismissed(0);
    setLingered(0);
    setFlash(true);
    const t = window.setTimeout(() => setFlash(false), 900);
    return () => window.clearTimeout(t);
  }, [hint]);

  const dismiss = () => {
    setDismissed(started);
    try {
      window.localStorage.setItem(DISMISS_KEY, String(started));
    } catch {
      // 写不进去就只影响下次打开时还记不记得，不影响这一轮
    }
  };

  const explain = () => {
    if (!failed.length) return;
    const text =
      failed.length === 1
        ? (failed[0].label + "：" + (failed[0].error || "没抓到")).slice(0, 140)
        : failed.length + " 个平台没抓到：" + failed.map((r) => r.label).join("、");
    window.dispatchEvent(
      new CustomEvent("onefeed:toast", {
        detail: { text, action: { label: "重试失败", run: () => onRetry(failed.map((r) => r.id)) } },
      }),
    );
  };

  return (
    <div
      aria-hidden={!show}
      onPointerEnter={() => setHover(true)}
      onPointerLeave={() => setHover(false)}
      style={{ width: show ? width : 0 }}
      className="absolute right-full top-1/2 -translate-y-1/2 overflow-hidden transition-[width] duration-300 ease-out"
    >
      <div ref={inner} className="w-max">
        <section
          data-refresh-bar="1"
          aria-live="polite"
          aria-busy={live}
          className={
            "relative mr-1.5 flex h-9 max-w-[min(62vw,440px)] items-center gap-1.5 overflow-hidden whitespace-nowrap rounded-full border border-line bg-wash/60 pl-3 pr-1 text-[12px] transition-shadow " +
            (flash ? "ring-2 ring-accent/35" : "")
          }
        >
          <span
            aria-hidden="true"
            className="pointer-events-none absolute inset-y-0 left-0 bg-accent/15 transition-[width] duration-500"
            style={{ width: fill + "%" }}
          />
          {live ? (
            <>
              <Loader2 size={13} className="relative shrink-0 animate-spin text-accent" />
              <span className="relative shrink-0 font-medium text-ink">{settling ? "整理中" : "正在抓"}</span>
              {settling ? null : runningLabel ? (
                <span className="relative hidden truncate text-muted sm:inline">{runningLabel}</span>
              ) : null}
              <span className="relative shrink-0 tabular-nums text-muted">{done}/{total}</span>
              <span className="relative hidden shrink-0 tabular-nums text-fade sm:inline">
                {settling ? "马上好" : elapsed + "s"}
              </span>
            </>
          ) : (
            <>
              <span className={"relative shrink-0 font-medium " + (newTotal > 0 ? "text-ink" : "text-muted")}>
                {newTotal > 0 ? "+" + newTotal + " 条" : "没有新增"}
              </span>
              <span className="relative hidden shrink-0 text-fade sm:inline">
                {newTotal > 0 ? "刚放进来了" : "抓完了"}
              </span>
            </>
          )}
          {failed.length ? (
            <button
              type="button"
              onClick={explain}
              title={failed.length === 1 ? failed[0].label + "：" + (failed[0].error || "没抓到") : "有平台没抓到"}
              className="relative flex h-7 shrink-0 items-center gap-0.5 rounded-full px-1 text-danger transition hover:bg-danger/10"
            >
              <AlertCircle size={13} />
              {failed.length > 1 ? <span className="tabular-nums text-[11px]">{failed.length}</span> : null}
            </button>
          ) : null}
          <button
            type="button"
            onClick={dismiss}
            aria-label="收起这一轮的进度"
            title="收起"
            className="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-fade transition hover:bg-wash hover:text-ink"
          >
            <X size={13} />
          </button>
        </section>
      </div>
    </div>
  );
}
