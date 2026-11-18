import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "framer-motion";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { DUR, SPRING } from "../../motion";

export interface RailItem {
  id: string;
  label: string;
  count?: number;
  tint?: string;
}

interface Props {
  /** 同一页里多个 rail 用不同 id，避免 layout 动画串味 */
  id: string;
  items: RailItem[];
  /** 选中的平台 id；空数组 = 全部 */
  value: string[];
  onChange: (next: string[]) => void;
  label: string;
}

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface ItemBox extends Box {
  inner: Box;
}

interface Run {
  /** 段首平台 id，用来和上一帧的段对上号 */
  key: string;
  /** 渲染身份：只有它变了，遮罩才会被卸载重挂（也就是丢掉动画） */
  id: string;
  items: RailItem[];
  box: Box;
}

const sameBox = (a: Box, b: Box) => a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h;

const sameBoxes = (a: Record<string, ItemBox>, b: Record<string, ItemBox>) => {
  const ka = Object.keys(a);
  const kb = Object.keys(b);
  if (ka.length !== kb.length) return false;
  for (const k of ka) {
    const x = a[k];
    const y = b[k];
    if (!y || !sameBox(x, y) || !sameBox(x.inner, y.inner)) return false;
  }
  return true;
};

/** chip 里的内容，正文层与遮罩副本层共用；tone 只换颜色，排版完全一致 */
function Inner({ item, inverted }: { item: RailItem; inverted: boolean }) {
  return (
    <span
      data-inner=""
      className={"flex items-center gap-1.5 " + (inverted ? "text-solid-fg" : "text-muted")}
    >
      {item.tint ? <span className="h-[7px] w-[7px] shrink-0 rounded-full" style={{ background: item.tint }} /> : null}
      {item.label}
      {item.count === undefined ? null : (
        <span className={"text-[11px] tabular-nums " + (inverted ? "text-solid-fg/60" : "text-fade")}>
          {item.count}
        </span>
      )}
    </span>
  );
}

/**
 * 选中高亮 = 独立遮罩层，文字层永远不动。
 *
 * 所有 chip 始终是同一排 button，父子关系在任何一次点击里都不变；
 * 遮罩是绝对定位的反色胶囊，只动画 x / width，里面放一份和正文逐像素重合的副本，
 * 副本跟着遮罩反向平移，所以看起来是「反色扫过去」，字形一次都没位移。
 */
function RunMask({
  run,
  boxes,
  railW,
  reduce,
}: {
  run: Run;
  boxes: Record<string, ItemBox>;
  railW: number;
  reduce: boolean;
}) {
  const x = useMotionValue(run.box.x);
  const w = useMotionValue(run.box.w);
  const counter = useTransform(x, (value) => -value);

  useEffect(() => {
    if (reduce) {
      x.set(run.box.x);
      w.set(run.box.w);
      return;
    }
    const move = animate(x, run.box.x, SPRING);
    const grow = animate(w, run.box.w, SPRING);
    return () => {
      move.stop();
      grow.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.box.x, run.box.w, reduce]);

  return (
    <motion.div
      aria-hidden
      className="pointer-events-none absolute left-0 z-10 overflow-hidden rounded-full bg-solid shadow-sm"
      style={{ x, width: w, top: run.box.y, height: run.box.h }}
    >
      {/* 副本层要按整条轨道的宽度铺开：子项用的是 rail 坐标，宽度被胶囊框住会把文字折行 */}
      <motion.div className="absolute top-0 left-0 h-full" style={{ x: counter, width: railW }}>
        {run.items.map((item) => {
          const inner = boxes[item.id]?.inner;
          if (!inner) return null;
          return (
            <div
              key={item.id}
              data-copy-of={item.id}
              className="absolute text-[13px] leading-none"
              style={{ left: inner.x, top: inner.y - run.box.y }}
            >
              <Inner item={item} inverted />
            </div>
          );
        })}
      </motion.div>
    </motion.div>
  );
}

/** 被合并 / 拆掉的那条胶囊：原地淡出，避免高亮凭空消失 */
function GhostMask({ box, items, boxes }: { box: Box; items: RailItem[]; boxes: Record<string, ItemBox> }) {
  return (
    <motion.div
      aria-hidden
      className="pointer-events-none absolute left-0 z-10 overflow-hidden rounded-full bg-solid shadow-sm"
      style={{ top: box.y, height: box.h }}
      initial={{ x: box.x, width: box.w, opacity: 1 }}
      animate={{ opacity: 0 }}
      transition={{ duration: DUR.base }}
    >
      {items.map((item) => {
        const inner = boxes[item.id]?.inner;
        if (!inner) return null;
        return (
          <div
            key={item.id}
            className="absolute text-[13px] leading-none"
            style={{ left: inner.x - box.x, top: inner.y - box.y }}
          >
            <Inner item={item} inverted />
          </div>
        );
      })}
    </motion.div>
  );
}

export default function TabRail({ items, value, onChange, label }: Props) {
  const reduce = useReducedMotion() ?? false;
  const rail = useRef<HTMLDivElement>(null);
  const anchor = useRef<string | null>(null);
  const [primary, setPrimary] = useState<string>("all");
  const [boxes, setBoxes] = useState<Record<string, ItemBox>>({});
  const [focused, setFocused] = useState<string | null>(null);
  const [ghosts, setGhosts] = useState<{ gid: string; run: Run; box: Box }[]>([]);
  const seen = useRef<Run[]>([]);

  const key = value.join(",");
  useEffect(() => {
    setPrimary((prev) => (value.length === 0 ? "all" : value.includes(prev) ? prev : value[0]));
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  const platforms = items.filter((item) => item.id !== "all").map((item) => item.id);
  const isOn = (item: RailItem) => (item.id === "all" ? value.length === 0 : value.includes(item.id));

  /** 量每个 chip 与 chip 内文字的盒子；只在尺寸真的变了才写 state，避免空转 */
  const measure = useCallback(() => {
    const root = rail.current;
    if (!root) return;
    const next: Record<string, ItemBox> = {};
    root.querySelectorAll<HTMLElement>("button[data-value]").forEach((button) => {
      const id = button.dataset.value;
      if (!id) return;
      const inner = button.querySelector<HTMLElement>("[data-inner]");
      next[id] = {
        x: button.offsetLeft,
        y: button.offsetTop,
        w: button.offsetWidth,
        h: button.offsetHeight,
        inner: inner
          ? {
              x: button.offsetLeft + inner.offsetLeft,
              y: button.offsetTop + inner.offsetTop,
              w: inner.offsetWidth,
              h: inner.offsetHeight,
            }
          : { x: button.offsetLeft, y: button.offsetTop, w: button.offsetWidth, h: button.offsetHeight },
      };
    });
    setBoxes((prev) => (sameBoxes(prev, next) ? prev : next));
  }, []);

  useLayoutEffect(() => {
    measure();
  }, [measure, items, value]);

  useEffect(() => {
    const root = rail.current;
    if (!root) return;
    const observer = new ResizeObserver(() => measure());
    observer.observe(root);
    for (const child of Array.from(root.children)) {
      if (child.tagName === "BUTTON") observer.observe(child);
    }
    const onFonts = () => measure();
    void document.fonts?.ready.then(onFonts).catch(() => undefined);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [measure, items]);

  const runs: Run[] = [];
  for (const item of items) {
    if (!isOn(item)) continue;
    const box = boxes[item.id];
    if (!box) continue;
    const last = runs[runs.length - 1];
    if (last && last.items[last.items.length - 1].id && railAdjacent(last.items[last.items.length - 1].id, item.id)) {
      last.items.push(item);
    } else {
      runs.push({ key: item.id, id: "", items: [item], box });
    }
  }
  for (const run of runs) {
    const first = boxes[run.items[0].id];
    const tail = boxes[run.items[run.items.length - 1].id];
    run.box = { x: first.x, y: first.y, w: tail.x + tail.w - first.x, h: first.h };
  }

  // 身份：只有同一段沿用同一个身份，遮罩组件才不会被卸载，动画才有起点
  const prevRuns = seen.current;
  const used = new Set<string>();
  for (const run of runs) {
    const old = prevRuns.find((each) => each.key === run.key && !used.has(each.id));
    if (old) {
      run.id = old.id;
      used.add(old.id);
    }
  }
  // 只剩一段时（全部 ↔ 单个平台、单个平台之间）：让同一个遮罩平移过去
  if (runs.length === 1 && !runs[0].id) {
    const free = prevRuns.find((each) => !used.has(each.id));
    if (free) {
      runs[0].id = free.id;
      used.add(free.id);
    }
  }
  // 其余按横向重叠继承（合并、拆分），没得继承才用段首 id
  for (const run of runs) {
    if (run.id) continue;
    const old = prevRuns.find((each) => {
      if (used.has(each.id)) return false;
      const overlap = Math.min(each.box.x + each.box.w, run.box.x + run.box.w) - Math.max(each.box.x, run.box.x);
      return overlap > 4;
    });
    run.id = old ? old.id : run.key;
    used.add(run.id);
  }

  // 消失的那条原地淡出
  const signature = runs.map((run) => run.id + ":" + run.items.length).join("|");
  useEffect(() => {
    const prev = seen.current;
    const live = new Set(runs.map((run) => run.id));
    const gone = prev.filter((run) => !live.has(run.id));
    seen.current = runs;
    if (!gone.length) return;
    const stamp = Date.now();
    setGhosts((old) => [...old, ...gone.map((run) => ({ gid: run.id + "@" + stamp, run, box: run.box }))]);
    const timer = window.setTimeout(() => {
      setGhosts((old) => old.filter((each) => !each.gid.endsWith("@" + stamp)));
    }, 260);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  const bring = (target: string) => {
    requestAnimationFrame(() => {
      rail.current?.querySelector<HTMLElement>('[data-value="' + target + '"]')?.scrollIntoView({ inline: "nearest", block: "nearest" });
    });
  };

  const choose = (target: string, mods: { ctrl: boolean; shift: boolean }) => {
    if (target === "all") {
      anchor.current = null;
      setPrimary("all");
      onChange([]);
      bring("all");
      return;
    }

    let next: string[];
    if (mods.shift && anchor.current && anchor.current !== target) {
      const from = platforms.indexOf(anchor.current);
      const to = platforms.indexOf(target);
      if (from >= 0 && to >= 0) {
        const [lo, hi] = from < to ? [from, to] : [to, from];
        const range = platforms.slice(lo, hi + 1);
        next = mods.ctrl ? Array.from(new Set([...value, ...range])) : range;
      } else {
        next = [target];
      }
    } else if (mods.ctrl) {
      next = value.includes(target) ? value.filter((each) => each !== target) : [...value, target];
      anchor.current = target;
    } else {
      next = value.length === 1 && value[0] === target ? [] : [target];
      anchor.current = target;
    }

    setPrimary(target);
    onChange(next);
    bring(target);
  };

  const step = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const order = ["all", ...platforms];
    const at = Math.max(0, order.indexOf(primary));
    const nextAt = event.key === "ArrowRight" ? Math.min(order.length - 1, at + 1) : Math.max(0, at - 1);
    const target = order[nextAt];
    choose(target, { ctrl: false, shift: false });
    rail.current?.querySelector<HTMLElement>('[data-value="' + target + '"]')?.focus();
  };

  const focusBox = focused ? boxes[focused] : undefined;
  const railW = Object.values(boxes).reduce((max, box) => Math.max(max, box.x + box.w), 0);

  return (
    <div className="w-fit max-w-full rounded-full border border-line bg-paper p-1">
      <div
        ref={rail}
        role="group"
        aria-label={label}
        onKeyDown={step}
        className="relative flex min-w-0 items-center gap-0.5 overflow-x-auto overscroll-x-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            data-value={item.id}
            aria-pressed={isOn(item)}
            tabIndex={primary === item.id ? 0 : -1}
            onClick={(event) => choose(item.id, { ctrl: event.ctrlKey || event.metaKey, shift: event.shiftKey })}
            onFocus={() => setFocused(item.id)}
            onBlur={() => setFocused((prev) => (prev === item.id ? null : prev))}
            className="relative z-0 shrink-0 rounded-full px-3 py-1.5 text-[13px] leading-none transition-colors duration-150 hover:bg-wash focus-visible:outline-none"
          >
            <Inner item={item} inverted={false} />
          </button>
        ))}

        {runs.map((run) => (
          <RunMask key={run.id} run={run} boxes={boxes} railW={railW} reduce={reduce} />
        ))}

        {ghosts.map((ghost) => (
          <GhostMask key={ghost.gid} box={ghost.box} items={ghost.run.items} boxes={boxes} />
        ))}

        {focusBox ? (
          <span
            aria-hidden
            className="pointer-events-none absolute z-20 rounded-full ring-2 ring-ink/25"
            style={{ left: focusBox.x, top: focusBox.y, width: focusBox.w, height: focusBox.h }}
          />
        ) : null}
      </div>
    </div>
  );
}

/** 平台在 rail 里的相邻关系：只和上一个 chip 挨着才算同一段 */
function railAdjacent(left: string, right: string) {
  const order = ["all", "bilibili", "xiaohongshu", "douyin", "juejin", "v2ex", "zhihu", "zhihu-hot"];
  return order.indexOf(right) - order.indexOf(left) === 1;
}
