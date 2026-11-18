import { ArrowUp, Loader2, Sparkles, Wand2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import type { AiResponse, FeedItem } from "../api";
import { aiChat } from "../api";
import { platform } from "../platform";
import FilterBox from "./FilterBox";

interface Turn {
  role: "user" | "ai";
  text: string;
  data?: AiResponse;
}

const HINTS = [
  "今天 B 站有什么 AI 的",
  "随便来点，别老是同一个平台",
  "这周小红书在聊什么",
];

/** 底部悬浮的 AI 入口：一句话找内容，也是"刷一刷"的入口。 */
export default function AiDock({ onOpenItem }: { onOpenItem: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [manual, setManual] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();

  useEffect(() => {
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [turns, busy]);

  const ask = async (message: string, exclude: string[] = []) => {
    const said = message.trim();
    if (!said || busy) return;
    setText("");
    setOpen(true);
    setBusy(true);
    setTurns((prev) => [...prev, { role: "user", text: said }]);
    try {
      const data = await aiChat(said, {
        exclude,
        history: turns.slice(-4).map((t) => ({
          role: t.role === "user" ? "user" : "assistant",
          text: t.text,
          plan: t.data?.plan,
        })),
      });
      setTurns((prev) => [...prev, { role: "ai", text: data.reply, data }]);
    } catch (err) {
      setTurns((prev) => [...prev, { role: "ai", text: err instanceof Error ? err.message : "请求失败" }]);
    } finally {
      setBusy(false);
    }
  };

  const last = [...turns].reverse().find((t) => t.role === "ai" && t.data)?.data;

  const applyFilter = (data: AiResponse) => {
    const detail = {
      platforms: data.plan.platforms,
      keyword: data.plan.keyword,
      range: data.plan.since ? "today" : "all",
      sort: data.plan.sort,
    };
    window.dispatchEvent(new CustomEvent("onefeed:filter", { detail }));
    setOpen(false);
  };

  return (
    <>
      <AnimatePresence>
        {open ? (
          <motion.div
            key="scrim"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduce ? 0 : 0.18 }}
            className="fixed inset-0 z-30 bg-solid/10 md:bg-transparent"
            onClick={() => setOpen(false)}
          />
        ) : null}
      </AnimatePresence>

      {/* 挂到 body：切页动画会给页面容器加 transform，fixed 元素留在里面会跟着跑 */}
      {createPortal(
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 flex justify-center px-4 pb-4">
        <div className="pointer-events-auto w-full max-w-[760px]">
          <AnimatePresence initial={false}>
          {open ? (
            <motion.div
              key="panel"
              initial={{ opacity: 0, y: 12, scale: 0.985 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 10, scale: 0.99 }}
              transition={{ duration: reduce ? 0 : 0.24, ease: [0.22, 1, 0.36, 1] }}
              className="mb-3 flex max-h-[62vh] flex-col overflow-hidden rounded-card border border-line bg-paper shadow-[0_18px_50px_rgba(20,20,20,0.14)]"
            >
              <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
                <Sparkles size={14} className="text-ink" />
                <span className="text-[13px] font-medium">找内容</span>
                <button
                  onClick={() => setOpen(false)}
                  className="ml-auto rounded p-1 text-fade transition hover:bg-wash hover:text-ink"
                  aria-label="收起"
                >
                  <X size={15} />
                </button>
              </div>

              <div ref={listRef} className="min-h-[180px] flex-1 space-y-4 overflow-y-auto px-4 py-4">
                {turns.length === 0 ? (
                  <div className="space-y-2">
                    <p className="text-[13px] text-muted">你可以直接说要什么，平台、时间、类型都算数。</p>
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
                      <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-solid px-3.5 py-2 text-[13px] text-solid-fg">
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
                          <p className="text-[13px] leading-relaxed">{turn.text}</p>
                          {turn.data ? (
                            <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[11px] text-fade">
                              <span className="rounded-full border border-line px-2 py-0.5">{turn.data.understood}</span>
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
                            <MiniRow key={item.id} item={item} onOpen={() => onOpenItem(item.id)} />
                          ))}
                        </div>
                      ) : null}

                      {turn.data ? (
                        <div className="flex flex-wrap items-center gap-2 pl-8">
                          <button
                            onClick={() => applyFilter(turn.data as AiResponse)}
                            className="rounded-full bg-solid px-3 py-1.5 text-[12px] text-solid-fg"
                          >
                            用这个条件刷
                          </button>
                          <button
                            onClick={() => void ask("再换一批", (turn.data as AiResponse).items.map((i) => i.id))}
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
                    </div>
                  ),
                )}

                {busy ? (
                  <div className="flex items-center gap-2 text-[12px] text-fade">
                    <Loader2 size={14} className="animate-spin" />
                    Agent 正在本地库里翻…
                  </div>
                ) : null}
              </div>

              <div className="border-t border-line px-4 py-2.5">
                <button
                  onClick={() => setManual((v) => !v)}
                  className="text-[12px] text-fade transition hover:text-ink"
                >
                  {manual ? "收起手动筛选" : "手动筛选"}
                </button>
                <AnimatePresence initial={false}>
                  {manual ? (
                    <motion.div
                      key="manual"
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: "auto", opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: reduce ? 0 : 0.22, ease: [0.22, 1, 0.36, 1] }}
                      style={{ overflow: "hidden" }}
                    >
                      <FilterBox
                        value=""
                        parsed={null}
                        onSubmit={(q) => {
                          window.dispatchEvent(new CustomEvent("onefeed:filter", { detail: { keyword: q } }));
                          setOpen(false);
                        }}
                      />
                    </motion.div>
                  ) : null}
                </AnimatePresence>
              </div>
            </motion.div>
          ) : null}
          </AnimatePresence>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void ask(text);
            }}
            className="flex h-12 items-center gap-2 rounded-full border border-line bg-paper/95 px-3 shadow-[0_10px_30px_rgba(20,20,20,0.12)] backdrop-blur transition focus-within:border-ink/30"
          >
            <span className="flex h-7 w-7 items-center justify-center rounded-full bg-solid text-solid-fg">
              <Wand2 size={14} />
            </span>
            <input
              ref={inputRef}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onFocus={() => setOpen(true)}
              placeholder="问 OneFeed：帮我把今天 B 站和知乎的 AI 内容挑出来"
              className="h-full flex-1 bg-transparent text-[13px] outline-none placeholder:text-fade"
            />
            {last ? (
              <button
                type="button"
                onClick={() => void ask("随便来点", last.items.map((i) => i.id))}
                className="hidden shrink-0 rounded-full border border-line px-2.5 py-1 text-[12px] text-muted transition hover:border-ink/25 hover:text-ink md:block"
              >
                刷一刷
              </button>
            ) : null}
            <button
              type="submit"
              disabled={busy || !text.trim()}
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-solid text-solid-fg transition disabled:opacity-30"
              aria-label="发送"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <ArrowUp size={15} />}
            </button>
          </form>
        </div>
      </div>,
      document.body,
      )}
    </>
  );
}

function MiniRow({ item, onOpen }: { item: FeedItem; onOpen: () => void }) {
  const p = platform(item.platform);
  return (
    <button
      onClick={onOpen}
      className="flex w-full items-start gap-2.5 rounded-lg border border-line/70 px-2 py-1.5 text-left transition hover:border-ink/20 hover:bg-wash/40"
    >
      {item.cover ? (
        <img src={item.cover} alt="" loading="lazy" referrerPolicy="no-referrer"
          className="h-12 w-16 shrink-0 rounded object-cover" />
      ) : (
        <span className="flex h-12 w-16 shrink-0 items-center justify-center rounded bg-wash text-[10px] text-fade">
          {p.label}
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="line-clamp-2 text-[12.5px] leading-snug">{item.title}</span>
        <span className="mt-1 flex flex-wrap items-center gap-x-2 text-[11px] text-fade">
          <span className="text-muted">{p.label}</span>
          {item.reasons.slice(0, 2).map((r) => (
            <span key={r}>{r}</span>
          ))}
        </span>
      </span>
    </button>
  );
}
