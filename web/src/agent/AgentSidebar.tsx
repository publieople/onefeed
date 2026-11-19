import {
  ChevronRight,
  HelpCircle,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  Settings,
  Sparkles,
  Star,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getJSON, type AgentThread, type FeedResponse } from "../api";
import { useAgentActions, useAgentHistory, useAgentSession } from "./AgentProvider";

/**
 * 左栏：Agent 工作台。
 * 只放「跟 Agent 有关」的东西 —— 会话史、新对话、收藏入口。导航菜单不往这里塞，
 * 它跟顶栏的设置 / 市场是两套东西，混在一起会变成又一个侧边导航。
 */
export default function AgentSidebar({
  collapsed = false,
  onExpand,
  onCollapse,
  onNavigate,
  onHelp,
}: {
  collapsed?: boolean;
  onExpand?: () => void;
  onCollapse?: () => void;
  onNavigate?: () => void;
  onHelp?: () => void;
}) {
  const { items, loading } = useAgentHistory();
  const { threadId, turns, busy } = useAgentSession();
  const { refreshHistory, resumeThread, newThread, openWith } = useAgentActions();
  const [query, setQuery] = useState("");
  const [savedCount, setSavedCount] = useState(0);

  useEffect(() => {
    void refreshHistory();
  }, [refreshHistory, threadId]);

  useEffect(() => {
    const load = () =>
      void getJSON<FeedResponse>("/api/feed?saved=1&limit=1")
        .then((data) => setSavedCount(data.count ?? 0))
        .catch(() => setSavedCount(0));
    load();
    window.addEventListener("onefeed:saved", load);
    return () => window.removeEventListener("onefeed:saved", load);
  }, []);

  const groups = useMemo(() => groupThreads(items, query), [items, query]);

  const start = () => {
    newThread();
    openWith();
    onNavigate?.();
  };

  const resume = (thread: AgentThread) => {
    void resumeThread(thread);
    onNavigate?.();
  };

  if (collapsed) {
    return (
      <aside
        aria-label="Agent 工作台（收起的图标栏）"
        className="flex h-full w-full flex-col items-center gap-1 py-2"
      >
        <button
          onClick={onExpand}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-muted transition hover:bg-wash hover:text-ink"
          aria-label="展开 Agent 工作台"
          title="展开（[）"
        >
          <PanelLeftOpen size={15} />
        </button>
        <button
          onClick={start}
          className="flex h-9 w-9 items-center justify-center rounded-lg bg-solid text-solid-fg transition hover:opacity-90"
          aria-label="新对话"
          title="新对话"
        >
          <Plus size={15} />
        </button>
        <div className="my-1 h-px w-6 bg-line" aria-hidden />
        <div className="flex min-h-0 flex-1 flex-col items-center gap-1 overflow-y-auto overscroll-contain [scrollbar-width:none]">
          {items.slice(0, 14).map((thread) => (
            <button
              key={thread.id}
              onClick={() => resume(thread)}
              title={thread.title}
              aria-label={"继续：" + thread.title}
              className={
                "flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-[11.5px] transition hover:bg-wash " +
                (thread.id === threadId ? "bg-wash text-ink" : "text-muted")
              }
            >
              {firstGlyph(thread.title)}
            </button>
          ))}
        </div>
        <button
          onClick={() => window.dispatchEvent(new CustomEvent("onefeed:rail", { detail: { tab: "saved" } }))}
          className="relative flex h-9 w-9 items-center justify-center rounded-lg text-muted transition hover:bg-wash hover:text-ink"
          aria-label={"稍后再看（" + savedCount + " 条）"}
          title="稍后再看（]）"
        >
          <Star size={15} />
          {savedCount ? (
            <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-ink" aria-hidden />
          ) : null}
        </button>
        <button
          onClick={onHelp}
          className="flex h-9 w-9 items-center justify-center rounded-lg text-muted transition hover:bg-wash hover:text-ink"
          aria-label="快捷键"
          title="快捷键（?）"
        >
          <HelpCircle size={15} />
        </button>
        <Link
          to="/settings"
          className="flex h-9 w-9 items-center justify-center rounded-lg text-muted transition hover:bg-wash hover:text-ink"
          aria-label="设置"
          title="设置"
        >
          <Settings size={15} />
        </Link>
      </aside>
    );
  }

  return (
    <aside
      aria-label="Agent 工作台"
      className="flex h-full w-72 shrink-0 flex-col overflow-hidden"
    >
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-3">
        <Sparkles size={14} className="text-muted" />
        <span className="text-[13px] font-medium">Agent 工作台</span>
        <button
          onClick={onCollapse}
          className="ml-auto flex h-7 w-7 items-center justify-center rounded-full text-fade transition hover:bg-wash hover:text-ink"
          aria-label="收起 Agent 工作台"
          title="收起（[）"
        >
          <PanelLeftClose size={14} />
        </button>
      </div>

      <div className="shrink-0 space-y-2 px-3 py-2.5">
        <button
          onClick={start}
          className="flex h-9 w-full items-center justify-center gap-1.5 rounded-lg bg-solid text-[12.5px] text-solid-fg transition hover:opacity-90"
        >
          <Plus size={14} />
          新对话
        </button>
        <label className="flex h-8 items-center gap-1.5 rounded-lg border border-line px-2 text-fade focus-within:border-ink/25">
          <Search size={12} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="找一段聊过的"
            aria-label="搜索对话"
            className="w-full bg-transparent text-[12px] text-ink outline-none placeholder:text-fade"
          />
        </label>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-2 pb-2">
        {loading && !items.length ? (
          <p className="flex items-center gap-2 px-2 py-6 text-[12px] text-fade">
            <Loader2 size={12} className="animate-spin" />
            正在翻…
          </p>
        ) : !items.length ? (
          <p className="px-2 py-6 text-[12px] leading-relaxed text-muted">
            还没聊过。按 / 说一句，这里就会记下来。
          </p>
        ) : !groups.length ? (
          <p className="px-2 py-6 text-[12px] text-muted">没有匹配的对话。</p>
        ) : (
          groups.map((group) => (
            <section key={group.label} className="mb-2">
              <h3 className="px-2 py-1 text-[11px] text-fade">{group.label}</h3>
              <ul className="space-y-0.5">
                {group.items.map((thread) => (
                  <li key={thread.id}>
                    <button
                      onClick={() => resume(thread)}
                      aria-current={thread.id === threadId ? "true" : undefined}
                      className={
                        "w-full rounded-lg px-2 py-1.5 text-left transition hover:bg-wash/80 " +
                        (thread.id === threadId ? "bg-wash text-ink" : "text-muted")
                      }
                    >
                      <span className="flex items-center gap-1.5">
                        {thread.id === threadId && busy ? (
                          <Loader2 size={10} className="shrink-0 animate-spin" />
                        ) : null}
                        <span className="truncate text-[12.5px] leading-[1.4]">{thread.title || "没起名的对话"}</span>
                      </span>
                      <span className="mt-0.5 flex items-center gap-1.5 text-[11px] text-fade">
                        {thread.runs} 轮
                        <span>·</span>
                        {relative(thread.updated_at)}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}
      </div>

      <div className="shrink-0 border-t border-line p-2">
        <button
          onClick={() => window.dispatchEvent(new CustomEvent("onefeed:rail", { detail: { tab: "saved" } }))}
          className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-[12px] text-muted transition hover:bg-wash hover:text-ink"
        >
          <Star size={13} />
          稍后再看
          <span className="ml-auto text-[11px] text-fade">{savedCount}</span>
        </button>
        <button
          onClick={onHelp}
          className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-[12px] text-muted transition hover:bg-wash hover:text-ink"
        >
          <HelpCircle size={13} />
          快捷键
          <kbd className="ml-auto rounded border border-line px-1 text-[10px] text-fade">?</kbd>
        </button>
        <Link
          to="/settings"
          className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-[12px] text-muted transition hover:bg-wash hover:text-ink"
        >
          <Settings size={13} />
          设置
        </Link>
        {turns.length ? (
          <p className="mt-1 flex items-center gap-1 px-2 text-[11px] text-fade">
            <ChevronRight size={10} />
            当前这段 {turns.filter((turn) => turn.role === "user").length} 轮
          </p>
        ) : null}
      </div>
    </aside>
  );
}

function firstGlyph(title: string): string {
  const trimmed = (title || "").trim();
  return trimmed ? Array.from(trimmed)[0] : "·";
}

/** 今天 / 昨天 / 更早：按最近一次更新时间分组，最新的在最上面 */
function groupThreads(items: AgentThread[], query: string) {
  const now = new Date();
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime() / 1000;
  const startOfYesterday = startOfToday - 86400;
  const q = query.trim();
  const buckets: { label: string; items: AgentThread[] }[] = [
    { label: "今天", items: [] },
    { label: "昨天", items: [] },
    { label: "更早", items: [] },
  ];
  for (const thread of items) {
    if (q && !thread.title.includes(q)) continue;
    const at = Number(thread.updated_at || 0);
    if (at >= startOfToday) buckets[0].items.push(thread);
    else if (at >= startOfYesterday) buckets[1].items.push(thread);
    else buckets[2].items.push(thread);
  }
  return buckets.filter((bucket) => bucket.items.length);
}

function relative(ts: number): string {
  const seconds = Date.now() / 1000 - Number(ts || 0);
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return Math.floor(seconds / 60) + " 分钟前";
  if (seconds < 86400) return Math.floor(seconds / 3600) + " 小时前";
  return Math.floor(seconds / 86400) + " 天前";
}
