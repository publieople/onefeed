import { ChevronDown, ListChecks, Loader2, Sparkles, Square, Star } from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";
import type { AgentEvent, FeedItem } from "../api";
import AgentConsole from "../components/AgentConsole";
import { platform } from "../platform";
import { scrollInstant } from "../motion/useSmoothWheelScroll";
import { HINTS, useAgentActions, useAgentSession } from "./AgentProvider";

/** 一轮对话的内容：用户气泡、Agent 的答复 + 轨迹 + 结果行 + 后续动作。三处形态共用。 */
export default function AgentThread({ padding = "px-4 py-4" }: { padding?: string }) {
  const { turns, busy, live, answered, answeredAsk, stopping, saved } = useAgentSession();
  const { ask, stop, confirm, answer, toggleSave, openItem, applyFilter } = useAgentActions();
  const listRef = useRef<HTMLDivElement | null>(null);

  // 新消息 / 轨迹更新都往下贴：过程在长，视线得跟着走
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    // 走缓动引擎的坐标系：直接赋 scrollTop 会被下一帧的旧 target 拉回去（实测 345→0→900ms 又回 345）。
    // immediate 写位置，不产生一次追不上的平滑滚动。
    scrollInstant(el, el.scrollHeight);
  }, [turns.length, busy, live?.events.length]);

  return (
    <div
      ref={listRef}
      aria-live="polite"
      aria-relevant="additions text"
      data-smooth-scroll
      className={"min-h-0 flex-1 space-y-4 overflow-y-auto " + padding}
    >
      {turns.length === 0 ? (
        <div className="space-y-2.5">
          <p className="text-[13px] text-muted">
            你可以直接说要什么，平台、时间、类型都算数；也可以让我总结当前这条。
          </p>
          <div className="flex flex-wrap gap-2">
            {HINTS.map((hint) => (
              <button
                key={hint}
                onClick={() => void ask(hint)}
                className="rounded-full border border-line px-3 py-1.5 text-[12px] text-muted transition hover:border-ink/25 hover:text-ink"
              >
                {hint}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {turns.map((turn, index) =>
        turn.role === "user" ? (
          <div key={index} className="rise flex justify-end">
            <div className="max-w-[80%] whitespace-pre-wrap rounded-2xl rounded-br-sm bg-solid px-3.5 py-2 text-[13px] text-solid-fg">
              {turn.text}
            </div>
          </div>
        ) : (
          <div key={index} className="rise space-y-2.5">
            <div className="flex items-start gap-2">
              <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-line">
                <Sparkles size={12} />
              </span>
              <div className="min-w-0">
                <p className="whitespace-pre-wrap text-[13px] leading-relaxed">{turn.text}</p>
                {turn.stopped ? (
                  <span className="mt-1 inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[11px] text-fade">
                    <Square size={8} fill="currentColor" />
                    按你点的停止收的尾
                  </span>
                ) : null}
                {turn.data ? (
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-fade">
                    {turn.data.understood ? (
                      <span className="rounded-full border border-line px-2 py-0.5">{turn.data.understood}</span>
                    ) : null}
                    <span>{turn.data.count} 条</span>
                    {turn.data.engine === "agent" && turn.data.steps ? (
                      <span className="text-fade/80">
                        自己查了 {turn.data.steps} 次
                        {turn.data.ms ? ` · ${(turn.data.ms / 1000).toFixed(1)}s` : ""}
                      </span>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>

            {turn.data?.items.length ? (
              <div className="space-y-1.5 pl-8">
                {turn.data.items.slice(0, 8).map((item) => (
                  <MiniRow
                    key={item.id}
                    item={item}
                    saved={saved.has(item.id)}
                    onToggleSave={() => void toggleSave(item.id)}
                    onOpen={() => openItem(item.id, item)}
                  />
                ))}
              </div>
            ) : null}

            {turn.data ? (
              <div className="flex flex-wrap items-center gap-2 pl-8">
                <button
                  onClick={() => applyFilter(turn.data!)}
                  className="rounded-full bg-solid px-3 py-1.5 text-[12px] text-solid-fg"
                >
                  用这个条件刷
                </button>
                <button
                  onClick={() => void ask("再换一批", turn.data!.items.map((i) => i.id))}
                  className="rounded-full border border-line px-3 py-1.5 text-[12px] text-muted transition hover:border-ink/25 hover:text-ink"
                >
                  换一批
                </button>
                {turn.data.suggestions.slice(0, 2).map((s) => (
                  <button
                    key={s}
                    onClick={() => void ask(s)}
                    className="rounded-full border border-line px-3 py-1.5 text-[12px] text-muted transition hover:border-ink/25 hover:text-ink"
                  >
                    {s}
                  </button>
                ))}
              </div>
            ) : null}

            {turn.trace?.length ? (
              <div className="pl-8">
                <TraceDisclosure
                  events={turn.trace}
                  answered={answered}
                  answeredAsk={answeredAsk}
                  readonly={turn.history}
                  ms={turn.data?.ms}
                />
              </div>
            ) : null}
          </div>
        ),
      )}

      {live ? (
        <div className="rise space-y-1.5">
          <AgentConsole
            events={live.events}
            running
            answered={answered}
            onConfirm={confirm}
            answeredAsk={answeredAsk}
            onAnswer={(askId, selected, free) => void answer(askId, selected, free)}
          />
          {/* 结果还没回来时先把形状占住：一轮可能要十几秒，底下空着会让人以为它答不出东西。
              骨架是装饰，别让读屏念出来。 */}
          <div className="space-y-1.5 pl-8" aria-hidden>
            <p className="text-[11px] text-fade">结果在回来的路上…</p>
            {[0, 1].map((row) => (
              <div
                key={row}
                className="flex animate-pulse items-center gap-2.5 rounded-lg border border-line/60 bg-wash/30 px-2 py-1.5"
              >
                <span className="h-12 w-16 shrink-0 rounded bg-wash" />
                <span className="flex-1 space-y-1.5">
                  <span className="block h-2.5 w-3/4 rounded bg-wash" />
                  <span className="block h-2 w-1/3 rounded bg-wash" />
                </span>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2 pl-1">
            <button
              onClick={() => void stop()}
              disabled={stopping}
              aria-label={stopping ? "正在停止" : "停止这一轮"}
              className="flex items-center gap-1 rounded-full border border-line px-2.5 py-1 text-[11px] text-fade transition hover:border-ink/25 hover:text-ink disabled:opacity-60"
            >
              {stopping ? <Loader2 size={11} className="animate-spin" /> : <Square size={9} fill="currentColor" />}
              {stopping ? "正在停止" : "停止"}
            </button>
          </div>
        </div>
      ) : null}

      {busy && !live ? (
        <div className="flex items-center gap-2 text-[12px] text-fade">
          <Loader2 size={14} className="animate-spin" />
          Agent 正在本地库里翻…
        </div>
      ) : null}
    </div>
  );
}

/**
 * 已经跑完的一轮，过程默认收起来：用户要的是结果，不是每一步。
 * 折叠行本身仍报出「几步 / 多久」，想复查再点开——展开的仍是同一个 AgentConsole。
 */
function TraceDisclosure({
  events,
  answered,
  answeredAsk,
  readonly,
  ms,
}: {
  events: AgentEvent[];
  answered?: Record<string, boolean>;
  answeredAsk?: Record<string, string[]>;
  readonly?: boolean;
  ms?: number;
}) {
  const [open, setOpen] = useState(false);
  const steps = events.filter(
    (event) =>
      event.kind === "step" ||
      event.kind === "action" ||
      event.kind === "need_confirm" ||
      event.kind === "need_answer" ||
      event.kind === "error",
  ).length;
  return (
    <div data-agent-trace={open ? "open" : "collapsed"}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        title={open ? "收起过程" : "展开过程"}
        className="flex items-center gap-1.5 rounded-full border border-line/70 px-2 py-1 text-[11px] text-fade transition hover:border-ink/25 hover:text-ink"
      >
        <ListChecks size={11} />
        <span>{steps ? `过程 ${steps} 步` : "过程"}</span>
        {ms ? <span className="tabular-nums text-fade/80">· {(ms / 1000).toFixed(1)}s</span> : null}
        <ChevronDown size={11} className={"transition-transform " + (open ? "rotate-180" : "")} />
      </button>
      {open ? (
        <div className="mt-1.5">
          <AgentConsole
            events={events}
            answered={answered}
            answeredAsk={answeredAsk}
            readonly={readonly}
          />
        </div>
      ) : null}
    </div>
  );
}

/** 结果行：点开详情 + 星标收藏，星标不经过模型 */
const MiniRow = memo(function MiniRow({
  item,
  saved,
  onOpen,
  onToggleSave,
}: {
  item: FeedItem;
  saved: boolean;
  onOpen: () => void;
  onToggleSave: () => void;
}) {
  const p = platform(item.platform);
  return (
    <div className="flex w-full items-start gap-1 rounded-lg border border-line/70 transition hover:border-ink/20 hover:bg-wash/40">
      <button onClick={onOpen} className="flex min-w-0 flex-1 items-start gap-2.5 px-2 py-1.5 text-left">
        {item.cover ? (
          <img
            src={item.cover}
            alt=""
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            className="h-12 w-16 shrink-0 rounded object-cover"
          />
        ) : (
          <span className="flex h-12 w-16 shrink-0 items-center justify-center rounded bg-wash text-[10px] text-fade">
            {p.label}
          </span>
        )}
        <span className="min-w-0 flex-1">
          <span className="line-clamp-2 text-[12.5px] leading-snug">{item.title}</span>
          <span className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] text-fade">
            <span className="text-muted">{p.label}</span>
            {(item.reasons || []).slice(0, 2).map((r) => (
              <span key={r}>{r}</span>
            ))}
          </span>
        </span>
      </button>
      <button
        type="button"
        onClick={onToggleSave}
        aria-pressed={saved}
        aria-label={saved ? "取消收藏" : "收藏这条"}
        title={saved ? "取消收藏" : "收藏"}
        className={"mr-1 mt-1.5 shrink-0 rounded p-1 transition hover:bg-wash active:scale-90 " + (saved ? "text-ink" : "text-fade hover:text-ink")}
      >
        <Star size={13} fill={saved ? "currentColor" : "none"} />
      </button>
    </div>
  );
});
