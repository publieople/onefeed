import { ArrowLeft, Plus, Sparkles } from "lucide-react";
import { useEffect } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import type { AgentThread as AgentThreadMeta } from "../api";
import { useAgentActions, useAgentHistory, useAgentSession } from "../agent/AgentProvider";
import AgentComposer from "../agent/AgentComposer";
import AgentThreadView from "../agent/AgentThread";

/**
 * 全页形态：/agent 或 /agent/:threadId。
 * 左栏是会话史，右边是当前这段 —— 坐下来连着聊十几轮、或者回看以前的对话都在这儿。
 */
export default function AgentPage() {
  const { threadId: routeThread } = useParams();
  const navigate = useNavigate();
  const { threadId, turns, busy } = useAgentSession();
  const { items, loading, running = [] } = useAgentHistory();
  const { loadHistory, resumeThread, newThread } = useAgentActions();

  useEffect(() => {
    document.title = "对话 · OneFeed";
    void loadHistory();
  }, [loadHistory]);

  /* 刷新 / 直接进来：localStorage 里那段对话还没铺开，先拉回来 */
  useEffect(() => {
    if (routeThread || !threadId || turns.length) return;
    void resumeThread({ id: threadId, title: "", runs: 0, updated_at: 0 });
  }, [routeThread, threadId, turns.length, resumeThread]);

  /* 带着 threadId 进来（分享、刷新、历史回退）：把那段铺回来 */
  useEffect(() => {
    if (!routeThread || routeThread === threadId) return;
    const found = items.find((t) => t.id === routeThread);
    if (found) {
      void resumeThread(found);
      return;
    }
    // 列表还没回来时先按 id 拉，标题等列表回来再补
    if (!loading) {
      const stub: AgentThreadMeta = { id: routeThread, title: "", runs: 0, updated_at: 0 };
      void resumeThread(stub);
    }
  }, [routeThread, threadId, items, loading, resumeThread]);

  const openThread = (item: AgentThreadMeta) => {
    navigate("/agent/" + encodeURIComponent(item.id), { replace: true });
    void resumeThread(item);
  };

  return (
    <div className="pt-6">
      <h1 className="sr-only">对话</h1>
      <div className="flex items-center gap-3 text-[12px] text-muted">
        <button
          onClick={() => navigate("/")}
          className="inline-flex items-center gap-1 rounded-full px-2 py-1 transition hover:bg-wash hover:text-ink"
        >
          <ArrowLeft size={13} />
          返回信息流
        </button>
        <span className="inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[11px] text-fade">
          <Sparkles size={10} />
          对话
        </span>
      </div>

      <div className="mt-4 grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        <aside className="hidden lg:block">
          <div className="flex items-center gap-2">
            <span className="text-[12px] font-medium">最近的对话</span>
            <button
              onClick={() => {
                newThread();
                navigate("/agent", { replace: true });
              }}
              className="ml-auto inline-flex items-center gap-1 rounded-full border border-line px-2 py-1 text-[11px] text-muted transition hover:border-ink/25 hover:text-ink"
            >
              <Plus size={11} />
              新对话
            </button>
          </div>
          <div className="mt-2 space-y-1">
            {items.map((item) => (
              <button
                key={item.id}
                onClick={() => openThread(item)}
                aria-current={item.id === threadId ? "true" : undefined}
                className={
                  "flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left transition " +
                  (item.id === threadId
                    ? "border-ink/25 bg-wash/60"
                    : "border-line/70 hover:border-ink/20 hover:bg-wash/40")
                }
              >
                <span className="min-w-0 flex-1 truncate text-[12.5px]">{item.title || "新对话"}</span>
                {running.includes(item.id) ? (
                  <span
                    className="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-accent"
                    title="后台还在跑"
                    aria-label="后台还在跑"
                  />
                ) : null}
                <span className="shrink-0 text-[11px] text-fade">{item.runs} 轮</span>
              </button>
            ))}
            {!items.length ? (
              <p className="rounded-lg border border-dashed border-line px-2.5 py-3 text-[12px] text-fade">
                {loading ? "正在翻…" : "还没有别的对话。"}
              </p>
            ) : null}
          </div>
        </aside>

        <section className="flex h-[calc(100vh-200px)] min-h-[460px] flex-col overflow-hidden rounded-card border border-line bg-paper">
          <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
            <Sparkles size={14} className="text-ink" />
            <span className="text-[13px] font-medium">{threadId ? "这段对话" : "新的对话"}</span>
            <span className="text-[11px] text-fade">{busy ? "正在跑…" : `${turns.length} 条消息`}</span>
          </div>
          <AgentThreadView padding="px-5 py-4" />
          <div className="border-t border-line p-3">
            <AgentComposer wide />
          </div>
        </section>
      </div>

      {/* 窄屏：左栏收起，历史放进一条横向滚动条 */}
      <div className="mt-4 lg:hidden">
        <div className="flex gap-2 overflow-x-auto pb-1">
          <Link
            to="/agent"
            onClick={() => newThread()}
            className="shrink-0 rounded-full border border-line px-3 py-1.5 text-[12px] text-muted"
          >
            新对话
          </Link>
          {items.map((item) => (
            <button
              key={item.id}
              onClick={() => openThread(item)}
              className={
                "shrink-0 rounded-full border px-3 py-1.5 text-[12px] transition " +
                (item.id === threadId
                  ? "border-ink/25 bg-wash/60 text-ink"
                  : "border-line text-muted hover:border-ink/25 hover:text-ink")
              }
            >
              {item.title || "新对话"}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
