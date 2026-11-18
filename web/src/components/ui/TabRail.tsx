import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "framer-motion";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { DUR, EASE, SPRING } from "../../motion";

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
  /** 动画起点：这一帧之前和它重叠的那几段的并集；不填就用 box */
  seed?: { x: number; w: number };
  /** 这一段是这一帧凭空新生的（点了个不相邻的平台），需要从窄条铺开 */
  born?: boolean;
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
  // 起点用「被它并进来的那几段」的并集：中间插一个时，胶囊一上来就盖住整段，
  // 否则会先从左边那段长过去，中间那个 chip 有几十毫秒还是白底，看着像抖了一下
  const seed = reduce ? run.box : (run.seed ?? run.box);
  const x = useMotionValue(seed.x);
  const w = useMotionValue(seed.w);
  const counter = useTransform(x, (value) => -value);

  useEffect(() => {
    if (reduce) {
      x.set(run.box.x);
      w.set(run.box.w);
      return;
    }
    // 合并/拆分后是新挂载的组件，起点已经在 useMotionValue 里设成 seed，直接往目标长
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

/**
 * 被合并 / 拆掉的那条胶囊。
 *
 * 被别段整条盖住时要保持不透明，等覆盖它的新胶囊长到位再一次性消失：
 * 否则它会先淡出、而新胶囊还没长到，那一段会先变回未选中（白底浅字），再重新变黑，看起来像抖了一下。
 */
function GhostMask({
  box,
  items,
  boxes,
  absorbed,
}: {
  box: Box;
  items: RailItem[];
  boxes: Record<string, ItemBox>;
  absorbed: boolean;
}) {
  return (
    <motion.div
      aria-hidden
      className="pointer-events-none absolute left-0 z-10 overflow-hidden rounded-full bg-solid shadow-sm"
      style={{ top: box.y, height: box.h }}
      initial={{ x: box.x, width: box.w, opacity: 1 }}
      animate={{ opacity: absorbed ? 1 : 0 }}
      transition={absorbed ? { duration: 0 } : { duration: DUR.base }}
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

/**
 * 新盖上某个 chip 时往外散的一圈淡影。
 *
 * 单独一层、不带文字，所以缩放不会把副本拉变形；放在遮罩下面（z-5），
 * 从 chip 原尺寸胀到 1.15 倍并淡出，配合胶囊自身的展开，看起来才是「扩散出来」。
 */
function BloomPill({ box, onDone }: { box: Box; onDone: () => void }) {
  return (
    <motion.span
      aria-hidden
      className="pointer-events-none absolute z-[5] rounded-full bg-solid"
      style={{ left: box.x, top: box.y, width: box.w, height: box.h }}
      initial={{ opacity: 0.34, scale: 1 }}
      animate={{ opacity: 0, scale: 1.15 }}
      transition={{ duration: DUR.list, ease: EASE }}
      onAnimationComplete={onDone}
    />
  );
}

export default function TabRail({ items, value, onChange, label }: Props) {
  const reduce = useReducedMotion() ?? false;
  const rail = useRef<HTMLDivElement>(null);
  const anchor = useRef<string | null>(null);
  const [primary, setPrimary] = useState<string>("all");
  const [boxes, setBoxes] = useState<Record<string, ItemBox>>({});
  const [focused, setFocused] = useState<string | null>(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  const [ghosts, setGhosts] = useState<{ gid: string; run: Run; box: Box; absorbed: boolean }[]>([]);
  const [blooms, setBlooms] = useState<{ bid: string; box: Box }[]>([]);
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

  // 轨道横向溢出时给两侧加渐隐，否则用户不知道右边还有平台（滚动条是被藏掉的）
  useEffect(() => {
    const root = rail.current;
    if (!root) return;
    const sync = () =>
      setEdges({
        left: root.scrollLeft > 4,
        right: root.scrollLeft + root.clientWidth < root.scrollWidth - 4,
      });
    sync();
    root.addEventListener("scroll", sync, { passive: true });
    const observer = new ResizeObserver(sync);
    observer.observe(root);
    return () => {
      root.removeEventListener("scroll", sync);
      observer.disconnect();
    };
  }, [items.length]);

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

  // 身份与起点按这一帧的选中状态分三种走法：
  // 1. 前后都只选一个（含「全部」）：沿用同一个遮罩，位置/宽度直接补间 → 平移过去；
  // 2. 多选、新点的那枚旁边已有选中：从已选中那段长过去（用已选项的并集做起点，不会露白）；
  // 3. 多选、左右都没选：从被点的 chip 中心扩散出一条新胶囊（配 bloom 淡影）。
  const prevRuns = seen.current;
  const firstPaint = prevRuns.length === 0;
  const prevSel = new Set(prevRuns.flatMap((run) => run.items.map((item) => item.id)));
  const nextSel = runs.flatMap((run) => run.items.map((item) => item.id));
  const slide = !firstPaint && prevSel.size <= 1 && nextSel.length <= 1;
  const used = new Set<string>();
  const overlaps = (a: Box, b: Box) => Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x) > 4;

  // 平移时不管隔多远都沿用同一块遮罩：它自己滑过去，而不是「旧的淡出、新的长出来」
  let slideId: string | null = null;
  if (slide && runs.length === 1) {
    const free = prevRuns.find((each) => !used.has(each.id));
    if (free) {
      runs[0].id = free.id;
      used.add(free.id);
      slideId = free.id;
    }
  }

  // 同段首沿用身份；剩下的按横向重叠继承（合并、拆分、没挪位置的段）
  for (const run of runs) {
    if (run.id) continue;
    const old = prevRuns.find((each) => each.key === run.key && !used.has(each.id));
    if (old) {
      run.id = old.id;
      used.add(old.id);
    }
  }
  for (const run of runs) {
    if (run.id) continue;
    const old = prevRuns.find((each) => !used.has(each.id) && overlaps(each.box, run.box));
    if (old) {
      run.id = old.id;
    } else {
      run.id = run.key;
    }
    used.add(run.id);
  }

  // 起点：带着已选中项一起变长的段，只从已选中那部分长（相邻扩散）；
  // 一个已选项都没有的新段，才从被点的 chip 中心扩散；
  // 纯拆分/收缩的段没有新项，从它原来盖住的旧段并集缩回去。
  const born: Run[] = [];
  for (const run of runs) {
    if (slideId && run.id === slideId) continue; // 平移：不设 seed，从当前 motion value 继续滑
    const carried = run.items.filter((item) => prevSel.has(item.id) && boxes[item.id]);
    const hasNew = run.items.some((item) => !prevSel.has(item.id));
    if (carried.length) {
      const first = boxes[carried[0].id];
      let minX = first.x;
      let maxR = first.x + first.w;
      for (const item of carried) {
        const box = boxes[item.id];
        minX = Math.min(minX, box.x);
        maxR = Math.max(maxR, box.x + box.w);
      }
      run.seed = { x: minX, w: maxR - minX };
      continue;
    }
    if (hasNew && !firstPaint) {
      const target = run.items.find((item) => item.id === primary) ?? run.items[0];
      const box = boxes[target.id];
      const w0 = Math.max(18, Math.min(30, Math.round(box.w * 0.45)));
      run.born = true;
      run.seed = { x: Math.round(box.x + box.w / 2 - w0 / 2), w: w0 };
      born.push(run);
      continue;
    }
    if (!firstPaint) {
      let minX = run.box.x;
      let maxR = run.box.x + run.box.w;
      for (const old of prevRuns) {
        const overlap = Math.min(old.box.x + old.box.w, run.box.x + run.box.w) - Math.max(old.box.x, run.box.x);
        if (overlap <= 4) continue;
        minX = Math.min(minX, old.box.x);
        maxR = Math.max(maxR, old.box.x + old.box.w);
      }
      run.seed = { x: minX, w: maxR - minX };
    }
  }

  // 消失的那条：被新胶囊整条盖住的保持不透明等接力，其余原地淡出。
  // 这里不能用「签名变了才跑」：单选平移会沿用同一个 id，签名（id:长度）恰好不变，
  // seen 停在上一帧，下一次多选就会把已选中的段误判成新生。每帧提交后都比一次，代价只是几次数组比较。
  useLayoutEffect(() => {
    const prev = seen.current;
    const live = new Set(runs.map((run) => run.id));
    const gone = prev.filter((run) => !live.has(run.id));
    // 只有「凭空从点击中心扩散」的那几枚才放淡影：相邻跟长、平移都不该再散一圈
    // （连点也只保留最近 8 个，不堆垃圾）
    if (prev.length && !reduce && born.length) {
      const fresh = born
        .flatMap((run) => run.items)
        .filter((item) => !prevSel.has(item.id) && boxes[item.id])
        .slice(0, 4);
      if (fresh.length) {
        const stamp = Date.now();
        setBlooms((old) =>
          [
            ...old,
            ...fresh.map((item, at) => ({ bid: item.id + "@" + stamp + ":" + at, box: boxes[item.id] })),
          ].slice(-8),
        );
      }
    }
    seen.current = runs;
    if (!gone.length) return;
    const covered = (target: Box) =>
      runs.some((run) => {
        const box = run.box;
        return (
          box.x <= target.x + 1 &&
          box.x + box.w >= target.x + target.w - 1 &&
          Math.abs(box.y - target.y) <= 1 &&
          Math.abs(box.h - target.h) <= 1
        );
      });
    const stamp = Date.now();
    const added = gone.map((run) => ({
      gid: run.id + "@" + stamp,
      run,
      box: run.box,
      absorbed: covered(run.box),
    }));
    setGhosts((old) => [...old, ...added]);
    // 这里不能把定时器写进 cleanup：下一次选择会立刻清掉它，幽灵胶囊会永久留在页面上
    window.setTimeout(
      () => setGhosts((old) => old.filter((each) => !each.gid.endsWith("@" + stamp))),
      added.some((each) => each.absorbed) ? 620 : 260,
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  });

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

  // 方向键只挪焦点，不选：以前挪一格就发一次 /api/feed，键盘用户没法先看一眼再决定。
  // 选中交给 Enter / Space（button 原生行为）。
  const step = (event: React.KeyboardEvent<HTMLDivElement>) => {
    // Esc 一键退回「全部」：多选状态被键盘困住时总得有条出路
    if (event.key === "Escape") {
      if (!value.length) return;
      event.preventDefault();
      choose("all", { ctrl: false, shift: false });
      rail.current?.querySelector<HTMLElement>('[data-value="all"]')?.focus();
      return;
    }
    const keys = ["ArrowLeft", "ArrowRight", "Home", "End"];
    if (!keys.includes(event.key)) return;
    event.preventDefault();
    const order = ["all", ...platforms];
    const at = Math.max(0, order.indexOf(focused ?? primary));
    const nextAt =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? order.length - 1
          : event.key === "ArrowRight"
            ? Math.min(order.length - 1, at + 1)
            : Math.max(0, at - 1);
    const target = order[nextAt];
    rail.current?.querySelector<HTMLElement>('[data-value="' + target + '"]')?.focus();
    bring(target);
  };

  const focusBox = focused ? boxes[focused] : undefined;
  const railW = Object.values(boxes).reduce((max, box) => Math.max(max, box.x + box.w), 0);

  return (
    <div className="relative w-fit max-w-full rounded-full border border-line bg-paper p-1">
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
            tabIndex={(focused ?? primary) === item.id ? 0 : -1}
            onClick={(event) => choose(item.id, { ctrl: event.ctrlKey || event.metaKey, shift: event.shiftKey })}
            onFocus={() => setFocused(item.id)}
            onBlur={() => setFocused((prev) => (prev === item.id ? null : prev))}
            className="relative z-0 shrink-0 rounded-full px-3 py-1.5 text-[13px] leading-none transition-colors duration-150 hover:bg-wash focus-visible:outline-none"
          >
            <Inner item={item} inverted={false} />
          </button>
        ))}

        {runs.map((run) => (
          // 段里 chip 数一变（合并 / 拆分）就重挂一次，让遮罩从 seed 长到目标几何
          <RunMask key={run.id + ":" + run.items.length} run={run} boxes={boxes} railW={railW} reduce={reduce} />
        ))}

        {blooms.map((bloom) => (
          <BloomPill
            key={bloom.bid}
            box={bloom.box}
            onDone={() => setBlooms((old) => old.filter((each) => each.bid !== bloom.bid))}
          />
        ))}

        {ghosts.map((ghost) => (
          <GhostMask key={ghost.gid} box={ghost.box} items={ghost.run.items} boxes={boxes} absorbed={ghost.absorbed} />
        ))}

        {focusBox ? (
          <span
            aria-hidden
            className="pointer-events-none absolute z-20 rounded-full ring-2 ring-ink/25"
            style={{ left: focusBox.x, top: focusBox.y, width: focusBox.w, height: focusBox.h }}
          />
        ) : null}
      </div>

      {edges.left ? (
        <span aria-hidden className="pointer-events-none absolute inset-y-1 left-1 z-30 w-7 rounded-l-full bg-gradient-to-r from-paper via-paper/80 to-transparent" />
      ) : null}
      {edges.right ? (
        <span aria-hidden className="pointer-events-none absolute inset-y-1 right-1 z-30 w-7 rounded-r-full bg-gradient-to-l from-paper via-paper/80 to-transparent" />
      ) : null}
    </div>
  );
}

/** 平台在 rail 里的相邻关系：只和上一个 chip 挨着才算同一段 */
function railAdjacent(left: string, right: string) {
  const order = ["all", "bilibili", "xiaohongshu", "douyin", "juejin", "v2ex", "zhihu", "zhihu-hot"];
  return order.indexOf(right) - order.indexOf(left) === 1;
}
