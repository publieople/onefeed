import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useModalScope } from "../motion/useModalScope";

export interface CardMenuItem {
  id: string;
  label: string;
  icon: ReactNode;
  onSelect: () => void;
  danger?: boolean;
}

const ITEM_H = 34;
const PAD = 5;

/**
 * 卡片右上角那个「⋯」弹出来的菜单。
 *
 * 挂 portal 而不是留在卡片里：卡片有容器查询和裁剪，菜单会跟着被切掉；
 * 定位按被点按钮的 rect 算，右对齐、下面放不下就翻到上面。
 * 关掉的路径要给全：点外面、Esc、滚动、窗口缩放 —— 菜单是 fixed 的，
 * 跟着页面滚会飘到别处，索性滚一下就关。
 */
export default function CardMenu({
  anchor,
  items,
  onClose,
}: {
  anchor: HTMLElement;
  items: CardMenuItem[];
  onClose: () => void;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const hadFocus = useRef(false);
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);
  // 菜单开着时键盘归菜单：否则 [ / t / ? 会在菜单背后改布局、切主题
  useModalScope(true);

  useLayoutEffect(() => {
    const rect = anchor.getBoundingClientRect();
    const width = 196;
    const height = items.length * ITEM_H + PAD * 2;
    const left = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8));
    const below = rect.bottom + 6;
    const top = below + height > window.innerHeight - 8 ? Math.max(8, rect.top - height - 6) : below;
    setPos({ left, top });
  }, [anchor, items.length]);

  // 焦点必须等 pos 落地之后再给：首次渲染 pos 还是 null，这一支直接 return null，
  // 菜单节点根本不存在 —— 在 layout effect 里同步 focus 会永远拿到 null，
  // 结果是菜单打开了、键盘却停在「更多操作」上（方向键也因此不动）。
  useEffect(() => {
    if (!pos) return;
    ref.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    hadFocus.current = true;
  }, [pos]);

  // 菜单关掉（Esc / 点外面 / 选了某一项）后焦点要回到那个「⋯」：
  // 菜单节点一卸载焦点就掉到 body，键盘用户得从头 Tab 一遍才能回到原处。
  useEffect(
    () => () => {
      if (hadFocus.current) anchor.focus({ preventScroll: true });
    },
    [anchor],
  );

  useEffect(() => {
    const onDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target) return;
      if (ref.current?.contains(target) || anchor.contains(target)) return;
      onClose();
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
      }
    };
    const close = () => onClose();
    document.addEventListener("pointerdown", onDown, true);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("pointerdown", onDown, true);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [anchor, onClose]);

  if (!pos) return null;

  const move = (delta: number) => {
    const nodes = Array.from(ref.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);
    if (!nodes.length) return;
    const at = nodes.indexOf(document.activeElement as HTMLElement);
    const next = (at + delta + nodes.length) % nodes.length;
    nodes[next]?.focus();
  };

  return createPortal(
    <div
      ref={ref}
      role="menu"
      aria-label="卡片操作"
      style={{ left: pos.left, top: pos.top, "--item-h": ITEM_H + "px" } as React.CSSProperties}
      onKeyDown={(event) => {
        if (event.key === "ArrowDown") {
          event.preventDefault();
          move(1);
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          move(-1);
        }
      }}
      className="rise fixed z-50 w-[196px] rounded-xl border border-line bg-paper p-1 shadow-[0_16px_40px_rgba(20,20,20,0.18)]"
    >
      {items.map((item) => (
        <button
          key={item.id}
          role="menuitem"
          onClick={() => {
            onClose();
            item.onSelect();
          }}
          className={
            "flex h-[34px] w-full items-center gap-2 rounded-lg px-2.5 text-left text-[12.5px] transition hover:bg-wash " +
            (item.danger ? "text-danger" : "text-ink")
          }
        >
          <span className="flex h-4 w-4 items-center justify-center text-muted" aria-hidden>
            {item.icon}
          </span>
          {item.label}
        </button>
      ))}
    </div>,
    document.body,
  );
}
