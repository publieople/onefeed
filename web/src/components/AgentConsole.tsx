import { Check, Loader2, ShieldAlert, X } from "lucide-react";
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
}

/** 一轮 Agent 的轨迹：想什么、查了什么、动了什么、要你确认什么。 */
export default function AgentConsole({ events, running, answered = {}, onConfirm }: Props) {
  const rows = events.filter((event) =>
    event.kind === "step" || event.kind === "action" || event.kind === "need_confirm" || event.kind === "error",
  );

  return (
    <div className="space-y-1.5 rounded-xl border border-line/70 bg-wash/40 px-2.5 py-2">
      {rows.length === 0 ? (
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
          下一步…
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

function ConfirmRow({
  event,
  answered,
  onConfirm,
}: {
  event: AgentEvent;
  answered?: boolean;
  onConfirm?: (confirmId: string, allow: boolean) => void;
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
