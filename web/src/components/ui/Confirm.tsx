import { useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { motion, useReducedMotion } from "framer-motion";
import { DUR, EASE } from "../../motion/tokens";
import { pushScope, popScope } from "../../motion/useHotkeys";

/**
 * 全站第一个真对话框。
 *
 * 之前五处破坏性操作（卸载插件、清 key、退出登录、恢复默认、删模型）点了就没了。
 * 这里做成一件事：**先问，问完再删**。同时把焦点管理一次做对——
 * 打开记住焦点、初始焦点落在「取消」而不是危险按钮、Tab 在面板内循环、Esc 取消、关掉把焦点还回去。
 */

export interface ConfirmOptions {
  title: string;
  /** 后果说明。写清「会发生什么」，不要写「确定吗」 */
  body?: string;
  confirmText?: string;
  cancelText?: string;
  tone?: "normal" | "danger";
  /** 必须一字不差输入这个词才能确认（清空所有 key 这类不可逆操作用） */
  requireTyping?: string;
}

interface Pending {
  opts: ConfirmOptions;
  resolve: (ok: boolean) => void;
}

/** 同一时刻只有一个确认框；重复请求时关掉上一个（当作取消） */
let pending: Pending | null = null;
let setHost: ((p: Pending | null) => void) | null = null;

export function confirmDialog(opts: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    const req = { opts, resolve };
    // 页面还没挂 ConfirmHost（或组件单独渲染时）退回原生 confirm，保证不会静默丢点击
    if (!setHost) {
      const ok = window.confirm([opts.title, opts.body].filter(Boolean).join("\n\n"));
      resolve(ok);
      return;
    }
    if (pending) pending.resolve(false);
    pending = req;
    setHost(req);
  });
}

/** 组件里这样用：const confirm = useConfirm(); if (!(await confirm({...}))) return; */
export function useConfirm(): (opts: ConfirmOptions) => Promise<boolean> {
  return useCallback((opts: ConfirmOptions) => confirmDialog(opts), []);
}

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

export function ConfirmHost() {
  const [req, setReq] = useState<Pending | null>(null);
  const [typed, setTyped] = useState("");
  const panelRef = useRef<HTMLDivElement | null>(null);
  const cancelRef = useRef<HTMLButtonElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const restoreRef = useRef<Element | null>(null);
  const reduce = useReducedMotion();
  const titleId = useId();
  const bodyId = useId();

  useEffect(() => {
    setHost = setReq;
    return () => {
      setHost = null;
      if (pending) {
        pending.resolve(false);
        pending = null;
      }
    };
  }, []);

  const close = useCallback((ok: boolean) => {
    const cur = pending;
    pending = null;
    setReq(null);
    setTyped("");
    cur?.resolve(ok);
    // 焦点还给触发者：删完一行之后焦点落在 body 上，键盘用户会直接迷路
    const back = restoreRef.current as HTMLElement | null;
    restoreRef.current = null;
    // 同步还焦点：rAF 在后台标签页会被节流，弹窗关了焦点却还挂在 body 上
    if (back && typeof back.focus === "function" && document.body.contains(back)) back.focus();
  }, []);

  // 确认框压一层 dialog：否则底下的全局键照常响应，「?」会在弹窗上再叠一个帮助层、
  // 「[」会把左栏收起来 —— 弹窗开着的时候，键盘应该只属于这个弹窗。
  useEffect(() => {
    if (!req) return;
    pushScope("dialog");
    return () => popScope("dialog");
  }, [req]);

  useEffect(() => {
    if (!req) return;
    restoreRef.current = document.activeElement;
    const needTyping = Boolean(req.opts.requireTyping);
    requestAnimationFrame(() => {
      (needTyping ? inputRef.current : cancelRef.current)?.focus();
    });
  }, [req]);

  const trap = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close(false);
      return;
    }
    if (e.key !== "Tab") return;
    const nodes = Array.from(panelRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []).filter(
      (n) => n.offsetParent !== null,
    );
    if (nodes.length === 0) return;
    const first = nodes[0];
    const last = nodes[nodes.length - 1];
    const active = document.activeElement as HTMLElement | null;
    if (e.shiftKey && (active === first || !panelRef.current?.contains(active))) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  };

  const opts = req?.opts;
  const needTyping = opts?.requireTyping ?? "";
  const canConfirm = !needTyping || typed.trim() === needTyping;

  // 关闭即时卸载：不依赖退出动画收尾（动画帧被节流时弹窗会卡在 DOM 里挡点击）
  if (!req || !opts) return null;

  return createPortal(
        <motion.div
          key="confirm"
          className="fixed inset-0 z-[60] flex items-center justify-center px-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: reduce ? 0 : DUR.micro, ease: EASE }}
          onKeyDown={trap}
        >
          <div
            className="absolute inset-0 bg-solid/25 backdrop-blur-[2px]"
            onClick={() => close(false)}
            aria-hidden="true"
          />
          <motion.div
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label={opts.title}
            aria-describedby={opts.body ? bodyId : undefined}
            initial={reduce ? false : { opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, y: 6, scale: 0.985 }}
            transition={{ duration: reduce ? 0 : DUR.base, ease: EASE }}
            className="relative w-full max-w-[400px] rounded-card border border-line bg-paper p-5 shadow-pop"
          >
            <h2 id={titleId} className="text-[16px] font-semibold text-ink">
              {opts.title}
            </h2>
            {opts.body ? (
              <p id={bodyId} className="mt-2 text-[13px] leading-relaxed text-muted">
                {opts.body}
              </p>
            ) : null}

            {needTyping ? (
              <label className="mt-4 block">
                <span className="text-[12px] text-muted">
                  输入 <b className="font-semibold text-ink">{needTyping}</b> 确认
                </span>
                <input
                  ref={inputRef}
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && canConfirm) {
                      e.preventDefault();
                      close(true);
                    }
                  }}
                  spellCheck={false}
                  autoComplete="off"
                  className="mt-1.5 h-9 w-full rounded-lg border border-line bg-wash px-3 text-[13px] text-ink outline-none focus-visible:ring-2 focus-visible:ring-ink/25"
                />
              </label>
            ) : null}

            <div className="mt-5 flex justify-end gap-2">
              <button
                ref={cancelRef}
                type="button"
                onClick={() => close(false)}
                className="h-9 rounded-full border border-line px-4 text-[13px] text-ink hover:bg-wash focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink/25"
              >
                {opts.cancelText ?? "取消"}
              </button>
              <button
                type="button"
                disabled={!canConfirm}
                onClick={() => close(true)}
                className={`h-9 rounded-full px-4 text-[13px] font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-40 ${
                  opts.tone === "danger"
                    ? "bg-danger text-danger-fg focus-visible:ring-danger/40"
                    : "bg-solid text-solid-fg focus-visible:ring-ink/25"
                }`}
              >
                {opts.confirmText ?? "确定"}
              </button>
            </div>
          </motion.div>
        </motion.div>,
    document.body,
  );
}
