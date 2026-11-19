import { ArrowUp, Loader2, Square, Wand2 } from "lucide-react";
import { motion } from "framer-motion";
import { useState } from "react";
import { DUR, SPRING_SOFT } from "../motion/tokens";
import { HINTS, useAgentActions, useAgentSession, useAgentSurface } from "./AgentProvider";

/**
 * 输入条：全站唯一一个能对 Agent 说话的地方。
 * 点它才展开（不是聚焦就弹），发送键在忙时原地变成停止键。
 */
export default function AgentComposer({ wide = false }: { wide?: boolean }) {
  const { busy, stopping, turns } = useAgentSession();
  const { open, hintIndex, draft, mode } = useAgentSurface();
  const { ask, stop, setDraft, inputRef } = useAgentActions();
  const [focused, setFocused] = useState(false);

  const last = [...turns].reverse().find((turn) => turn.role === "ai" && turn.data)?.data;
  const expanded = open || mode === "rail" || mode === "sheet" || wide;

  return (
    <motion.form
      onSubmit={(e) => {
        e.preventDefault();
        void ask(draft);
      }}
      animate={{ scale: focused ? 1.012 : 1, y: focused ? -1 : 0 }}
      transition={SPRING_SOFT}
      className={
        "flex h-12 items-center gap-2 border bg-paper/95 px-3 transition-[border-color,box-shadow,border-radius] duration-200 " +
        (expanded ? "rounded-[22px] " : "rounded-full ") +
        (focused
          ? "border-ink/35 shadow-[0_12px_34px_rgba(20,20,20,0.16)]"
          : "border-line shadow-[0_10px_30px_rgba(20,20,20,0.12)]")
      }
    >
      <motion.span
        animate={{ rotate: focused ? -10 : 0, scale: focused ? 1.06 : 1 }}
        transition={SPRING_SOFT}
        className="flex h-7 w-7 items-center justify-center rounded-full bg-solid text-solid-fg"
      >
        <Wand2 size={14} />
      </motion.span>
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        aria-label="向 OneFeed 提问"
        placeholder={"问 OneFeed：" + HINTS[hintIndex]}
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
      {/* 同一个位置：不忙时是「发送」，忙时变「停止」——不用去面板里找那颗按钮 */}
      {busy ? (
        <motion.button
          key="stop"
          type="button"
          onClick={() => void stop()}
          disabled={stopping}
          whileTap={stopping ? undefined : { scale: 0.9 }}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-solid text-solid-fg transition disabled:opacity-60"
          aria-label={stopping ? "正在停止" : "停止这一轮"}
          title={stopping ? "正在停止…" : "停止这一轮"}
        >
          {stopping ? (
            <Loader2 size={15} className="animate-spin" />
          ) : (
            <motion.span
              key="square"
              initial={{ scale: 0.6, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ duration: DUR.micro }}
              className="flex"
            >
              <Square size={11} fill="currentColor" />
            </motion.span>
          )}
        </motion.button>
      ) : (
        <motion.button
          key="send"
          type="submit"
          disabled={!draft.trim()}
          whileTap={draft.trim() ? { scale: 0.9 } : undefined}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-solid text-solid-fg transition disabled:opacity-30"
          aria-label="发送"
        >
          <motion.span
            initial={{ y: 6, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: DUR.fast }}
            className="flex"
          >
            <ArrowUp size={15} />
          </motion.span>
        </motion.button>
      )}
    </motion.form>
  );
}
