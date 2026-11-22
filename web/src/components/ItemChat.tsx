import { motion, useReducedMotion } from "framer-motion";
import { ArrowUp, Loader2, MessageCircle, RotateCcw, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  streamItemChat,
  type ItemChatTurn,
  type SummaryDepth,
  type SummaryPayload,
} from "../api";
import { DUR, EASE } from "../motion/tokens";

interface Turn extends ItemChatTurn {
  /** 用户自己按了停止：留半句比吞掉更诚实 */
  stopped?: boolean;
}

interface Props {
  itemId: string;
  /** 当前档位，带过去让模型知道用户看到的是哪一版总结 */
  depth: SummaryDepth | "";
  /** 已经生成的总结：模型拿它当上下文，不用再问「你说哪条」 */
  summary: SummaryPayload | null;
}

const SUGGESTIONS = ["最值得记住的是哪一点", "有什么没讲清的地方", "这条和同题其他平台说法一样吗"];

/** 空对话时的开场白：给三个可以直接点的问法，省得盯着输入框想 */
function Starters({ onPick, disabled }: { onPick: (text: string) => void; disabled: boolean }) {
  const reduce = useReducedMotion();
  return (
    <div className="flex flex-wrap gap-1.5">
      {SUGGESTIONS.map((text, index) => (
        <motion.button
          key={text}
          type="button"
          disabled={disabled}
          onClick={() => onPick(text)}
          initial={reduce ? false : { opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: DUR.base, ease: EASE, delay: reduce ? 0 : index * 0.04 }}
          className="rounded-full border border-line px-2.5 py-1 text-[12px] text-muted transition-colors hover:border-ink/25 hover:text-ink disabled:opacity-50"
        >
          {text}
        </motion.button>
      ))}
    </div>
  );
}

/**
 * 就当前这条内容提问。挂在总结下面，和顶部那个「找内容」不是一回事：
 * 那边是全库 Agent，这边只谈这一条，所以素材、总结、历史都随请求带上。
 * 关闭 / 停止都走「立刻收尾」——不依赖出场动画，标签页被节流时也不会卡在 DOM 里。
 */
export default function ItemChat({ itemId, depth, summary }: Props) {
  const reduce = useReducedMotion();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [live, setLive] = useState("");
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<"thinking" | "writing" | "">("");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState("");
  const [focused, setFocused] = useState(false);

  const listRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const cancelRef = useRef<(() => void) | null>(null);
  /** 每次发送 +1：取消或换题之后，旧流的回调直接作废 */
  const runToken = useRef(0);
  const acc = useRef("");
  const startedAt = useRef(0);

  /* 换条目等于换话题：上一组的问答留着只会让人误会 */
  useEffect(() => {
    runToken.current += 1;
    cancelRef.current?.();
    cancelRef.current = null;
    acc.current = "";
    setTurns([]);
    setLive("");
    setBusy(false);
    setPhase("");
    setError("");
  }, [itemId]);

  useEffect(
    () => () => {
      runToken.current += 1;
      cancelRef.current?.();
    },
    [],
  );

  /* 新内容一律滚到底：这条是对话，最新的必须在眼前 */
  useEffect(() => {
    const el = listRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [turns.length, live, phase]);

  useEffect(() => {
    if (!busy) return;
    const timer = window.setInterval(() => {
      const now = typeof performance !== "undefined" ? performance.now() : Date.now();
      setSeconds((now - startedAt.current) / 1000);
    }, 250);
    return () => window.clearInterval(timer);
  }, [busy]);

  const send = (raw: string) => {
    const question = raw.trim();
    if (!question || busy || !itemId) return;
    const token = ++runToken.current;
    const history: ItemChatTurn[] = turns.slice(-6).map((t) => ({ role: t.role, text: t.text }));
    setTurns((prev) => prev.concat({ role: "user", text: question }));
    setInput("");
    setError("");
    setPhase("");
    setSeconds(0);
    setBusy(true);
    acc.current = "";
    setLive("");
    startedAt.current = typeof performance !== "undefined" ? performance.now() : Date.now();
    cancelRef.current = streamItemChat(
      itemId,
      { message: question, depth: depth || undefined, summary, history },
      {
        onStatus: (status) => {
          if (runToken.current !== token) return;
          if (status === "thinking") setPhase("thinking");
        },
        onDelta: (text) => {
          if (runToken.current !== token) return;
          setPhase("writing");
          acc.current += text;
          setLive(acc.current);
        },
        onDone: () => {
          if (runToken.current !== token) return;
          cancelRef.current = null;
          const answer = acc.current;
          acc.current = "";
          setLive("");
          setBusy(false);
          setPhase("");
          if (answer) setTurns((prev) => prev.concat({ role: "assistant", text: answer }));
        },
        onError: (message) => {
          if (runToken.current !== token) return;
          cancelRef.current = null;
          const partial = acc.current;
          acc.current = "";
          setLive("");
          setBusy(false);
          setPhase("");
          setError(message);
          if (partial) setTurns((prev) => prev.concat({ role: "assistant", text: partial, stopped: true }));
        },
      },
    );
  };

  /* 停止：本地立刻收尾，不等流那边慢慢断。半句话留着，比整段消失好 */
  const stop = () => {
    runToken.current += 1;
    cancelRef.current?.();
    cancelRef.current = null;
    const partial = acc.current;
    acc.current = "";
    setLive("");
    setBusy(false);
    setPhase("");
    setTurns((prev) => prev.concat({ role: "assistant", text: partial || "停下了。", stopped: true }));
    inputRef.current?.focus();
  };

  const reset = () => {
    runToken.current += 1;
    cancelRef.current?.();
    cancelRef.current = null;
    acc.current = "";
    setTurns([]);
    setLive("");
    setBusy(false);
    setPhase("");
    setError("");
    setInput("");
    inputRef.current?.focus();
  };

  const waiting = busy && !live;
  const sending = Boolean(input.trim());

  return (
    <section className="mt-5 rounded-xl border border-line" aria-label="就这条内容提问">
      <header className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <MessageCircle size={13} className="text-muted" />
        <span className="text-[12.5px] font-medium">问问这条</span>
        <span className="text-[11px] text-fade">只谈当前这条，不带别的</span>
        {turns.length ? (
          <button
            type="button"
            onClick={reset}
            className="ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] text-muted transition-colors hover:bg-wash hover:text-ink"
          >
            <RotateCcw size={10} />
            清空
          </button>
        ) : null}
      </header>

      <div ref={listRef} className="max-h-[360px] overflow-y-auto px-4 py-3" aria-live="polite">
        {turns.length === 0 && !live ? (
          <div className="space-y-2.5">
            <p className="text-[12px] leading-relaxed text-muted">
              看到不懂的地方直接问，答案只依据这条的素材和上面的总结。
            </p>
            <Starters onPick={send} disabled={busy} />
          </div>
        ) : (
          <ul className="space-y-3">
            {turns.map((turn, index) => (
              <motion.li
                key={index}
                initial={reduce ? false : { opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: DUR.base, ease: EASE }}
                className={turn.role === "user" ? "flex justify-end" : "flex justify-start"}
              >
                <div
                  className={
                    turn.role === "user"
                      ? "max-w-[86%] rounded-2xl rounded-br-md bg-solid px-3.5 py-2 text-[13px] leading-[1.7] text-solid-fg"
                      : "max-w-[92%] rounded-2xl rounded-bl-md bg-wash px-3.5 py-2 text-[13px] leading-[1.75] text-ink/90"
                  }
                >
                  <span className="whitespace-pre-wrap">{turn.text}</span>
                  {turn.stopped ? (
                    <span className="mt-1 block text-[10.5px] text-fade">按你点的停止收的尾</span>
                  ) : null}
                </div>
              </motion.li>
            ))}

            {live ? (
              <li className="flex justify-start">
                <div className="max-w-[92%] rounded-2xl rounded-bl-md bg-wash px-3.5 py-2 text-[13px] leading-[1.75] text-ink/90">
                  <span className="whitespace-pre-wrap">{live}</span>
                  <span className="ml-0.5 inline-block h-[1.05em] w-[2px] translate-y-[2px] animate-pulse bg-ink/40 align-baseline" />
                </div>
              </li>
            ) : null}

            {waiting ? (
              <li className="flex items-center gap-2 text-[12px] text-muted">
                <Loader2 size={12} className="animate-spin" />
                <span>{phase === "thinking" ? "正在想…" : "正在读这条…"}</span>
                {seconds >= 1 ? <span className="tabular-nums text-fade">{seconds.toFixed(0)}s</span> : null}
              </li>
            ) : null}
          </ul>
        )}

        {error ? (
          <p className="mt-2.5 rounded-lg bg-danger/10 px-2.5 py-1.5 text-[12px] leading-relaxed text-danger">{error}</p>
        ) : null}
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          send(input);
        }}
        className="border-t border-line px-3 py-2.5"
      >
        <motion.div
          initial={false}
          animate={reduce ? undefined : { scale: focused ? 1.006 : 1 }}
          transition={{ duration: DUR.micro, ease: EASE }}
          className={
            "flex items-end gap-2 rounded-xl border bg-paper px-2.5 py-1.5 transition-[border-color,box-shadow] duration-150 " +
            (focused ? "border-ink/30 shadow-[0_2px_12px_rgba(0,0,0,0.06)]" : "border-line")
          }
        >
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(event) => {
              setInput(event.target.value);
              const el = event.currentTarget;
              el.style.height = "auto";
              el.style.height = Math.min(96, el.scrollHeight) + "px";
            }}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                event.preventDefault();
                send(input);
              }
            }}
            placeholder={busy ? "等它说完，或者按右边的停止" : "就这条继续问…"}
            aria-label="就这条内容提问"
            disabled={busy}
            className="max-h-[96px] min-h-[24px] flex-1 resize-none bg-transparent text-[13px] leading-[1.7] outline-none placeholder:text-fade disabled:opacity-60"
          />
          {busy ? (
            <button
              type="button"
              onClick={stop}
              aria-label="停止回答"
              className="mb-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-solid text-solid-fg transition-transform active:scale-90"
            >
              <Square size={9} fill="currentColor" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!sending}
              aria-label="发送问题"
              className={
                "mb-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition-all duration-150 " +
                (sending
                  ? "bg-solid text-solid-fg hover:scale-105 active:scale-95"
                  : "bg-wash text-fade")
              }
            >
              <ArrowUp size={14} />
            </button>
          )}
        </motion.div>
      </form>
    </section>
  );
}
