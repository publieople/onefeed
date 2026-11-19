import { Check, ListChecks, Loader2, ShieldAlert, X } from "lucide-react";
import { useState } from "react";
import type { AgentEvent } from "../api";
import { platform } from "../platform";

const ACTION_LABELS: Record<string, string> = {
  ui_filter: "切换筛选",
  ui_navigate: "跳转页面",
  ui_open_item: "打开详情",
  ui_toast: "提示",
  save_item: "收藏",
  mark_read: "标记",
  refresh_feed: "触发采集",
};

interface Props {
  events: AgentEvent[];
  running?: boolean;
  /** 已答复的确认，避免重复点 */
  answered?: Record<string, boolean>;
  onConfirm?: (confirmId: string, allow: boolean) => void;
  /** 客户端回过的提问：ask_id → 选了什么（回放时用来显示结果） */
  answeredAsk?: Record<string, string[]>;
  onAnswer?: (askId: string, selected: string[], text: string) => void;
  /** 历史回放：轨迹只读，别让旧问卷再变成可点的按钮 */
  readonly?: boolean;
}

/** 一轮 Agent 的轨迹：打算怎么做、想什么、查了什么、动了什么、问你什么。 */
export default function AgentConsole({
  events,
  running,
  answered = {},
  onConfirm,
  answeredAsk = {},
  onAnswer,
  readonly = false,
}: Props) {
  const plan = events.find((event) => event.kind === "plan");
  // 正在等用户回答时，底部不该再说「下一步…」——下一步是用户
  const openAsk = events
    .filter((event) => event.kind === "need_answer")
    .filter((event) => answeredAsk[String(event.data.ask_id)] === undefined)
    .pop();
  const steps: string[] = Array.isArray(plan?.data?.steps) ? plan.data.steps.map(String) : [];
  const rows = events.filter(
    (event) =>
      event.kind === "step" ||
      event.kind === "action" ||
      event.kind === "need_confirm" ||
      event.kind === "need_answer" ||
      event.kind === "error",
  );

  return (
    <div className="space-y-1.5 rounded-xl border border-line/70 bg-wash/40 px-2.5 py-2">
      {steps.length ? (
        <div className="mb-1 space-y-1 border-b border-line/60 pb-1.5">
          <div className="flex items-center gap-1.5 text-[11.5px] text-muted">
            <ListChecks size={12} />
            <span>打算这么做</span>
          </div>
          <ol className="space-y-0.5 pl-[18px] text-[11.5px] leading-snug text-ink/85">
            {steps.map((step, i) => (
              <li key={i} className="list-decimal">
                {step}
              </li>
            ))}
          </ol>
        </div>
      ) : null}

      {rows.length === 0 && !readonly ? (
        <div className="flex items-center gap-1.5 text-[11.5px] text-fade">
          <Loader2 size={11} className="animate-spin" />
          正在想…
        </div>
      ) : null}

      {rows.map((event) =>
        event.kind === "need_confirm" ? (
          <ConfirmRow
            key={event.seq}
            event={event}
            answered={answered[String(event.data.confirm_id)]}
            onConfirm={onConfirm}
            readonly={readonly}
          />
        ) : event.kind === "need_answer" ? (
          <AskRow
            key={event.seq}
            event={event}
            picked={answeredAsk[String(event.data.ask_id)]}
            running={running}
            onAnswer={onAnswer}
            readonly={readonly}
          />
        ) : event.kind === "error" ? (
          <div key={event.seq} className="text-[11.5px] leading-snug text-[color:var(--warn,#b4432b)]">
            这轮没跑完：{String(event.data.message ?? "").slice(0, 120)}
          </div>
        ) : event.kind === "action" ? (
          <div key={event.seq} className="flex items-start gap-1.5 text-[11.5px] text-muted">
            <span className="mt-[5px] h-1 w-1 shrink-0 rounded-full bg-ink/50" />
            <span>{actionText(event)}</span>
          </div>
        ) : (
          <div key={event.seq} className="flex items-start gap-1.5 text-[11.5px] text-muted">
            <span className="mt-[5px] h-1 w-1 shrink-0 rounded-full bg-ink/70" />
            <span className="min-w-0">
              <span className="text-ink">{String(event.data.title ?? event.name)}</span>
              {event.data.kind === "think" && event.data.detail ? (
                <span className="ml-1 text-fade">「{String(event.data.detail).slice(0, 60)}」</span>
              ) : null}
            </span>
          </div>
        ),
      )}

      {running ? (
        <div className="flex items-center gap-1.5 pt-0.5 text-[11px] text-fade">
          <span className="h-1 w-1 animate-pulse rounded-full bg-ink/60" />
          {openAsk ? "等你选一下，或直接回一句" : "下一步…"}
        </div>
      ) : null}
    </div>
  );
}

function actionText(event: AgentEvent): string {
  const label = ACTION_LABELS[event.name] ?? event.name;
  const payload = (event.data?.payload ?? {}) as Record<string, unknown>;
  if (event.name === "ui_filter") {
    const platforms = Array.isArray(payload.platforms) ? payload.platforms.map((p) => platform(String(p)).label) : [];
    const bits = [
      platforms.length ? platforms.join("、") : "全部平台",
      payload.since === "today" ? "今天" : "",
      payload.keyword ? "含「" + String(payload.keyword) + "」" : "",
    ].filter(Boolean);
    return label + " · " + bits.join(" · ");
  }
  if (event.name === "ui_open_item" && payload.id) return label + " · " + String(payload.id);
  if (event.name === "ui_toast" && payload.text) return label + " · " + String(payload.text);
  return label;
}

function AskRow({
  event,
  picked,
  running,
  onAnswer,
  readonly,
}: {
  event: AgentEvent;
  picked?: string[];
  running?: boolean;
  onAnswer?: (askId: string, selected: string[], text: string) => void;
  readonly?: boolean;
}) {
  const askId = String(event.data.ask_id ?? "");
  const options: string[] = Array.isArray(event.data.options)
    ? event.data.options.map(String)
    : [];
  const multi = Boolean(event.data.multi);
  const allowFree = event.data.allow_free !== false;
  const settled = picked !== undefined;
  const [chosen, setChosen] = useState<string[]>([]);
  const [free, setFree] = useState("");
  const [sent, setSent] = useState(false);

  const send = (selected: string[], text: string) => {
    if (sent) return;
    setSent(true);
    onAnswer?.(askId, selected, text);
  };

  const toggle = (option: string) => {
    if (settled) return;
    if (!multi) {
      // 单选一问一答：点一下就算答完，别让用户再找一次「就这个」
      setChosen([option]);
      send([option], "");
      return;
    }
    setChosen((prev) =>
      prev.includes(option) ? prev.filter((x) => x !== option) : [...prev, option],
    );
  };

  return (
    <div className="rounded-lg border border-line bg-paper px-2.5 py-2">
      <div className="flex items-start gap-1.5 text-[11.5px]">
        <span className="mt-[3px] h-1.5 w-1.5 shrink-0 rounded-full bg-ink/70" />
        <span className="min-w-0 text-ink">{String(event.data.question ?? "")}</span>
      </div>

      {settled ? (
        <div className="mt-1.5 flex items-center gap-1 text-[11px] text-fade">
          <Check size={11} />
          你回了：{picked.length ? picked.join("、") : "（没选）"}
        </div>
      ) : readonly ? (
        <div className="mt-1.5 text-[11px] text-fade">这轮没等到你的回答</div>
      ) : (
        <>
          {options.length ? (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {options.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => toggle(option)}
                  aria-pressed={chosen.includes(option)}
                  className={`rounded-full border px-2.5 py-1 text-[11px] transition ${
                    chosen.includes(option)
                      ? "border-ink bg-solid text-solid-fg"
                      : "border-line text-muted hover:border-ink/25 hover:text-ink"
                  }`}
                >
                  {option}
                </button>
              ))}
            </div>
          ) : null}
          <div className="mt-1.5 flex items-center gap-1.5">
            {allowFree || !options.length ? (
              <input
                value={free}
                onChange={(e) => setFree(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    send(chosen, free.trim());
                  }
                }}
                aria-label="直接回一句"
                placeholder={options.length ? "或者直接说" : "回一句"}
                className="h-7 min-w-0 flex-1 rounded border border-line bg-transparent px-2 text-[11.5px] outline-none placeholder:text-fade focus:border-ink/30"
              />
            ) : null}
            <button
              type="button"
              onClick={() => send(chosen, free.trim())}
              disabled={!chosen.length && !free.trim()}
              className="shrink-0 rounded-full bg-solid px-2.5 py-1 text-[11px] text-solid-fg disabled:opacity-40"
            >
              {running === false ? "回一句" : "就这个"}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function ConfirmRow({
  event,
  answered,
  onConfirm,
  readonly,
}: {
  event: AgentEvent;
  answered?: boolean;
  onConfirm?: (confirmId: string, allow: boolean) => void;
  readonly?: boolean;
}) {
  const confirmId = String(event.data.confirm_id ?? "");
  const settled = typeof answered === "boolean";
  return (
    <div className="rounded-lg border border-line bg-paper px-2.5 py-2">
      <div className="flex items-start gap-1.5 text-[11.5px]">
        <ShieldAlert size={13} className="mt-[1px] shrink-0" />
        <span className="min-w-0">
          <span className="block text-ink">{String(event.data.summary ?? "这一步会动外部数据")}</span>
          {event.data.risk ? <span className="mt-0.5 block text-fade">{String(event.data.risk)}</span> : null}
        </span>
      </div>
      {settled ? (
        <div className="mt-1.5 flex items-center gap-1 text-[11px] text-fade">
          {answered ? <Check size={11} /> : <X size={11} />}
          {answered ? "已允许" : "没允许，它按现有数据继续"}
        </div>
      ) : readonly ? (
        <div className="mt-1.5 text-[11px] text-fade">这轮没等到你的确认</div>
      ) : (
        <div className="mt-1.5 flex gap-1.5">
          <button
            onClick={() => onConfirm?.(confirmId, true)}
            className="rounded-full bg-solid px-2.5 py-1 text-[11px] text-solid-fg"
          >
            允许
          </button>
          <button
            onClick={() => onConfirm?.(confirmId, false)}
            className="rounded-full border border-line px-2.5 py-1 text-[11px] text-muted transition hover:border-ink/25 hover:text-ink"
          >
            不用
          </button>
        </div>
      )}
    </div>
  );
}
