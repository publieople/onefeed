# 列位可配置 + 卡片自适应 + 左右栏开合流动动画（方案）

> 日期：2026-11-19 · 状态：方案（未施工）· 关联：`docs/side-rails-2026-11-19.md`

## 0. 三条前提判断

1. **列数必须按「内容列实测宽度」算，不能按视口宽度算。**
   现在网格写死 `md:grid-cols-2 xl:grid-cols-3`（`web/src/pages/FeedPage.tsx:297`），依据的是视口。左右栏一落地，视口 1440 时内容列只剩 ~1072，`xl:3` 仍按 1280 阈值生效，三列每列 344 变成 344 还是 344 —— 但 5 列、4 列的配置在这种差距下会彻底算错。所以断点从媒体查询搬到 ResizeObserver。

2. **改宽度只能「一帧跳到位」，流动感交给卡片的 FLIP，不能动画宽度。**
   侧栏宽度做 CSS/spring 动画 = 每帧重新布局 30 张卡（之前 4324px 高的 `.page-shell` 已经证明过这类全局重排的代价）。正确顺序：宽度离散切换 → 卡片从旧位置投影到新位置（transform，GPU）。

3. **配置存 localStorage，不进 URL。**
   URL 现在承载的是「可分享的筛选状态」（`?p=bilibili&q=...`，`FeedPage.tsx:22-46`）。每行几列是设备/屏幕偏好，写进 URL 会污染历史记录，而且换设备应该重新自适应。代价：不同步到别的机器，可接受。

---

## 1. 栏位数配置

### 1.1 数据模型

```ts
// web/src/layout/useGridCols.ts
export type ColsChoice = "auto" | 1 | 2 | 3 | 4 | 5;
export const COLS_KEY = "onefeed.feed.cols";   // 与 onefeed.agent.thread / theme 键同一命名族
export const GAP = 20;          // gap-x-5，与 FeedPage.tsx:297 一致
export const CARD_MIN = 216;    // 再窄标题两行会掉字，且 meta 会换行
export const CARD_TARGET = 380; // auto 模式的目标卡宽
```

### 1.2 计算公式

```ts
const maxFit = Math.max(1, Math.floor((W + GAP) / (CARD_MIN + GAP)));
const autoCols = Math.min(4, Math.max(1, Math.round(W / CARD_TARGET)));
const cols = choice === "auto" ? Math.min(autoCols, maxFit) : Math.min(choice, maxFit);
```

内容宽 1180（当前 `main` 的 `max-w-[1180px]`）时的落点：

| 选择 | 结果列数 | 单卡宽 | 备注 |
|---|---|---|---|
| 自动 | 3 | 380 | 与今天视觉一致 |
| 1 | 1 | 1180 | 需要媒体高度上限（见 2.3） |
| 2 | 2 | 580 | 偏宽但可读 |
| 3 | 3 | 380 | |
| 4 | 4 | 280 | |
| 5 | 5 | 220 | maxFit=(1180+20)/236=5，刚好放得下，属紧凑档 |

- 用户选了 5 但当前内容宽只够 4：**不静默降级**，在选项旁标「这宽度最多 4 列」，实际按 4 渲染。宽度变大后仍按 5 生效（因为存的是用户意图）。
- 初次渲染拿不到 ResizeObserver 结果：`useState` 初始化时同步量 `document.getElementById("main")?.clientWidth ?? window.innerWidth - 48`，避免首帧 1 列再跳成 3 列（用户明确反感这种位移）。

### 1.3 落地方式

```tsx
const { cols, maxFit } = useGridCols(gridRef, choice);

<section
  ref={gridRef}
  className="mt-5 grid items-stretch gap-x-5 gap-y-5"
  style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
>
```

- 删除 `md:grid-cols-2 xl:grid-cols-3`（`FeedPage.tsx:297`），骨架网格（`:333`）用同一个 `cols`，否则加载完会跳一次。
- `useGridCols` 内部：`ResizeObserver` 监听网格自身（不是 window），左右栏改宽时自动重算；用 `requestAnimationFrame` 合并一帧内的多次回调；卸载时 `disconnect`。
- 监听 `window` 的 `storage` 事件：另一个标签页改列数时跟随。

### 1.4 配置入口

**主入口：信息流工具条**（`FeedPage.tsx:255-267` 的「已收藏」右侧）

- 按钮：`Columns3` 图标 + 当前值文案（「自动」/「4 列」），`aria-haspopup="dialog"`。
- 弹层：`role="radiogroup" aria-label="每行卡片数"`，六个选项（自动 / 1 / 2 / 3 / 4 / 5），每项左侧一根三竖条示意，`aria-checked`；超出 `maxFit` 的选项 `aria-disabled` 并附「这宽度最多 N 列」。
- 关：Esc、点外部、选中即关（`useHotkeys("dialog", { escape })`，与 AI 面板同一套栈）。
- 键盘：`Alt+1`…`Alt+5`、`Alt+0` 回自动。**不用** Ctrl/⌘+数字：Chrome 用它切标签页。

**次入口：设置页新增「外观」节**（`web/src/pages/SettingsPage.tsx` 的 `SECTIONS` 里加一项），放同一个控件 + 「恢复自动」。理由：工具条是高频入口，设置页是「我忘了怎么改」时的兜底。

**守门**：`web/scripts/check-ui.mjs` 加两条——FeedPage 里禁止出现 `grid-cols-2`/`grid-cols-3` 字面量；网格必须带 `gridTemplateColumns`。

---

## 2. 卡片自适应缩放

现状是「按 340px 卡宽调好的固定尺」：标题 `h-[46px] text-[16px]`（`Card.tsx:274`）、meta `h-[43px] text-[13px]`（`:198`）、根 `min-h-[16rem] p-3`（`:250`）。5 列时 220px 卡里 16px 标题两行会被截；1 列时 1180px 卡里 16px 标题像小广告，媒体区 664px 高。

### 2.1 用一个查询容器 + cqw，不用逐卡 JS

- **查询容器挂在卡片外壳**（`data-vt-item` 那层），不是卡片根：`style={{ containerType: "inline-size" }}`。
- 卡片内部所有尺寸改用 `clamp(下限, Ncqw, 上限)`，`cqw` 相对外壳宽度，天然跟列数走，零 JS、零逐卡测量。
- 兼容性：`cqw` / `container-type` 在 Chrome 105+、Safari 16+、Firefox 110+。`theme.css` 里加 `@supports not (container-type: inline-size)` 回落到今天的固定值，老浏览器表现不变。

### 2.2 三处关键改动

| 位置 | 现在 | 改成 |
|---|---|---|
| 标题 `Card.tsx:274` | `h-[46px] text-[16px] leading-[1.42]` | `h-[2.84em] text-[clamp(14px,4.6cqw,18px)] leading-[1.42]` |
| MetaLine `Card.tsx:198/209` | `h-[43px] text-[13px]/[12px]` | `h-[2.8em] text-[clamp(11.5px,3.6cqw,13px)]` |
| 卡片根 `Card.tsx:250` | `min-h-[16rem] p-3` | `min-h-[14rem] p-[clamp(9px,3.2cqw,13px)]` |

`h-[2.84em]` 的妙处：`em` 相对标题自己的字号，两行 `1.42` 行高正好 2.84em，槽位随档位自动长高，**等高契约不破**（同一行列数相同 → 卡宽相同 → 字号相同 → 槽高相同）。

实测换算（`4.6cqw`）：220px→10.1px 被夹到 14px；280→12.9→14；380→17.5；580→26.7 被夹到 18。等价于三档：紧凑 220–300 / 常规 300–430 / 宽敞 ≥430。

### 2.3 媒体区与 1 列场景

- 保持 `aspect-video`（`Card.tsx:45`），因为它是等高契约的锚。
- 只加一个上限：宽敞档（卡宽 ≥430）`max-h-[420px]` + 现有 `object-cover`，1 列时媒体不会变成 664px 的巨幅。
- 更彻底的 1 列横向卡（媒体居左 40%、文字居右）列为 P2，不进这轮——它会改 `data-vt=media` 的几何，进而动共享元素转场。

### 2.4 骨架同步

骨架块（`FeedPage.tsx:335`）现在写死 `min-h-[340px]`。改成同样挂 `container-type` + 用同一套 `clamp` 高度，列数用同一个 `cols`。

---

## 3. 左右栏开合时的卡片流动动画

### 3.1 动画的物理顺序（关键）

侧栏开合分两步，**不能合并**：

1. **宽度离散切换**：内容列在一帧内从 1072 变 848（或反之），DOM 只提交一次。
2. **卡片 FLIP**：卡片从旧位置以 transform 滑到新位置，时长 `DUR.base`（0.24s）。

这样浏览器只重排一次；如果去动画 `width`/`grid-template-columns`，就是 0.24s × 60fps ≈ 14 次全量重排，30 张卡的媒体、标题、meta 全部逐帧重算，掉帧几乎必然。

### 3.2 代码形态

```tsx
// 一个 state 管所有影响几何的东西，保证一次 commit
const [layout, setLayout] = useState({ cols: "auto", left: "full", right: false });
const layoutKey = `${cols}:${layout.left}:${layout.right}`;

<LayoutGroup id="feed">
  <section style={{ gridTemplateColumns: `repeat(${cols}, minmax(0,1fr))` }}>
    {items.map((item, i) =>
      animateReflow ? (
        <motion.div
          key={item.id}
          data-vt-item={item.id}
          layout="position"
          layoutDependency={layoutKey}
          transition={{ duration: DUR.base, ease: EASE }}
          className="rise h-full"
          style={{ containerType: "inline-size" }}
        >
          <Card … />
        </motion.div>
      ) : ( <div … /> )
    )}
  </section>
</LayoutGroup>
```

四个要点：

- `layout="position"`：只投位置，不投尺寸。**尺寸动画会让 framer 用 scale 模拟宽高变化**，标题和缩略图在 0.24s 里被横向压扁，这比瞬间换宽度更难看。
- `layoutDependency={layoutKey}`：只在列数/侧栏变化时重测，feed 数据刷新、轮询重渲染都不触发（否则每次刷新卡片都滑一遍）。
- `LayoutGroup`：把同组测量隔离，避免右栏 Agent 列表里的 layout 动画与信息流互相干扰。
- 门槛：`animateReflow = items.length <= 48 && !reduce`。现在是 `<= 12`（`FeedPage.tsx:123`），穷举到 48 是因为 `layout="position"` 只写 transform，成本远低于原来的整卡布局投影；超过 48 直接瞬切。

### 3.3 侧栏自身的动画

- **左栏 288 ↔ 64**：宽度离散切换，内部文字标签 `opacity 0→1`（`DUR.fast`）配合，卡片同时 FLIP。用户看到的是「侧栏展开、内容让位、卡片滑过去」，而不是「侧栏把卡片一帧一帧挤走」。
- **右栏抽屉**：`transform: translateX`（`SPRING_SOFT`）+ 内容列宽度**不变**（抽屉浮在内容上方）→ 信息流不需要重排，这条路径最便宜。
- **右栏 ≥1800 入栅格**（`side-rails` 方案里的三栏态）：这时它和左栏一样走「离散改宽 + FLIP」。

### 3.4 三个必须处理的坑

1. **与 View Transition 打架**：导航转场进行中（`html.vt-running`）如果同时触发侧栏 FLIP，两套 transform 会互相覆盖。守卫：`if (document.documentElement.classList.contains("vt-running")) 跳过 FLIP，直接瞬切`。
2. **滚动锚定**：列数变少 → 行数变多 → 文档变高，视口顶部那张卡会「往上飘」。提交后立刻在 `useLayoutEffect` 里做锚定：记录变化前第一张跨过视口顶的卡片 `{id, top}`，变化后 `window.scrollBy(0, el.getBoundingClientRect().top - top)`。这发生在绘制前，用户看不到跳动，而 FLIP 的起点仍是卡片视觉原位，动画依旧正确。
3. **hover 与 layout 抢 transform**：`whileHover={{ y: -2 }}`（`Card.tsx:247`）在 FLIP 期间会被 layout 的 transform 覆盖。可接受（悬停感短暂丢失），若要更干净，FLIP 期间把 hover 换成 `box-shadow` 变化。

### 3.5 明确不采用的两条路

- **CSS 过渡 `grid-template-columns`**：Chrome 能对 `fr` 插值，但每帧重排，Firefox/Safari 行为不一致，且卡片内容会被逐帧挤压。
- **View Transition 做列变化**：需要给每张卡一个唯一 `view-transition-name`（30 个名字 = 30 层快照），并且会和现有 `of-media` / `of-title` 的转场命名冲突（同名会让浏览器整段跳过转场，这条坑 11-19 已经踩过）。

---

## 4. 分批与验收

| 批次 | 内容 | 工作量 |
|---|---|---|
| 1 | `useGridCols` + 内联网格 + 工具条弹层 + localStorage + 骨架同步 + 守门 | 0.5 天 |
| 2 | 卡片三档缩放（container-type + cqw + em 槽位 + 媒体上限 + @supports 回落） | 0.5 天 |
| 3 | LayoutGroup 重排动画 + 侧栏离散改宽 + 滚动锚定 + vt-running 守卫 + 降级 | 0.5 天 |

验收清单：

1. 内容宽 1180：自动 = 3 列；选 5 列 = 220px；选 1 列 = 1180px。
2. 1480 视口开左栏（288）：列数由 3 变 2（或用户固定值被 maxFit 夹住），卡片有 0.24s 位移过渡，无整页闪动。
3. 关右栏抽屉：内容列宽度不变（抽屉是浮层），信息流不重排。
4. 改列数后刷新：列数保持；换标签页（storage 事件）跟随。
5. 骨架与真卡列数一致，加载完成零位移（CLS 增量 ≈ 0）。
6. `prefers-reduced-motion`：无 FLIP、无侧栏动画，直接到位。
7. 48 张卡开合侧栏：无 >50ms 长任务；用 PerformanceObserver 记录 LayoutShift 次数。
8. 窄屏 <1024：固定 1 列，侧栏走 Sheet，不出现 2 列挤字。

## 5. 风险

- **`container-type: inline-size` 带来 layout containment**：元素会成为 `position: absolute` 后代的包含块。卡片内的绝对定位元素都在 `Frame`（`relative`）里，不受影响；但要复核 popover / tooltip 是否被塞进卡片内（目前没有）。
- **220px 卡的信息密度**：平台徽标 + 相对时间会挤，必要时 5 列档隐藏时间、只留徽标。
- **`layoutDependency` 漏传**：如果哪天列数从别处改（比如设置页），必须同时改 `layoutKey`，否则卡片瞬切。建议把 `cols` 只从 `LayoutProvider` 出，设置页和工具条都走同一个 setter。
- **首帧实测宽度**：`main` 有 `px-6`，网格宽度 = `main.clientWidth - 48`。初始化函数里要减掉，否则 1 列时算成 2 列。
---

## 6. 落地记录（2026-11-19，已实现并验证）

### 6.1 实际改了什么

| 文件 | 内容 |
|---|---|
| `web/src/layout/useGridCols.ts`（新） | 列数算法 + `ResizeObserver` 观察网格自身 + `localStorage`（`onefeed.feed.cols`）。导出 `maxFitCols` / `autoColsFor` / `GRID_GAP` / `CARD_MIN`，首帧用 `#main.clientWidth - 48` 垫底 |
| `web/src/components/ui/ColsPicker.tsx`（新） | 工具条按钮 + 弹层（`role="group" aria-label="每行卡片数"`、`aria-pressed`）；宽度不够的档位右侧标「最多 N 列」并在底部补一句说明；Esc / 点外部关闭（`pushScope("dialog")` + `useHotkeys("dialog", { escape })`） |
| `web/src/pages/FeedPage.tsx` | 网格改内联 `repeat(cols, minmax(0, 1fr))`；删掉 `md:/xl:` 断点；j/k/h/l 的跨列步长改用 `grid.cols`；Alt+0~5；`LayoutGroup` + `layoutDependency={grid.cols}`；`captureAnchor` / `chooseCols` / 补偿滚动；阈值 12 → 48；`useReducedMotion` 直接到位 |
| `web/src/components/Card.tsx` | 根节点 `container-type: inline-size`；`p-3` → `.card-pad`；标题 `h-[46px] text-[16px]` → `.card-title`（`clamp(14px, 4.6cqw, 18px)` + `height: 2.84em`）；meta → `.card-meta`；媒体 `max-h-[420px]` |
| `web/src/theme.css` | `.card-pad/.card-title/.card-meta/.card-meta-quiet` 的 cqw 规则 + `@supports not (container-type: inline-size)` 固定档回落 |
| `tests/test_grid_cols.py`（新） | 5 条静态守门：宽算列、弹层可达、卡片缩放、重排不被进场动画压住、换列保位置 |

### 6.2 方案里没写、施工时才暴露的四件事

1. **`.rise` 会永久压住 FLIP 的 transform。** 进场动画是 `animation: rise .34s ... both`，`fill-mode: both` 让最终帧的 `transform: translate3d(0,0,0)` 一直挂着，而 CSS 动画的优先级高于行内样式 —— framer 写进 `style.transform` 的位移被覆盖成 0，表现是「换列瞬间跳位、完全没有流动」。修法：把 `.rise` 移到内层 div，`motion.div`（layout 节点）只负责位置。
2. **滚动锚定必须记文档坐标。** 第一版记的是 `getBoundingClientRect().top`（视口坐标），补偿量把当前 `scrollY` 一起算了进去：滚到 1400 换列，页面直接跳到 0。改成 `top + window.scrollY` 后再比，实测目标卡从 `top: -12, scrollY: 1400` → `top: -12, scrollY: 2257`，视觉上原地不动。
3. **捕获时机要在改状态之前。** 「第一张还在视野里的卡」只有在换列前测才准，所以 `captureAnchor()` 放在 `chooseCols()` 里、`setChoice` 之前；弹层点选与 Alt+数字走同一个函数，不会有一条路径漏掉。
4. **实测宽度和方案里的 1180 差 48。** `main` 有 `px-6`，1280 视口下网格实测 1132；`maxFit = floor((1132 + 20) / 236) = 4`，所以 5 列要内容宽 ≥ 1160 才放得下。方案里「1180 → 5 列 220px」在真实布局里是 4 列 268px —— 数字以实测为准。

### 6.3 真机数字（Chrome 1280×860，924 条）

| 选择 | 实际列数 | 卡宽 | 标题字号 | 封面高 | 行高一致 |
|---|---|---|---|---|---|
| 自动 | 3 | 364 | 15.46px | 189 | 368 / 368 |
| 4 列 | 4 | 268 | 14px | 135 | 309 / 310（不同行） |
| 2 列 | 2 | 556 | 18px | 297 | 485 |
| 1 列 | 1 | 1132 | 18px | **420（封顶）** | 608 |

- 换列 FLIP：逐帧采样到 `matrix(1,0,0,1,96,0)` → `58.8` → `19.1` → `0.24` → `none`，约 0.24s（`DUR.base`）。
- 窄屏 900：自动落 2 列（416px / 17.85px），弹层对 4、5 列标「最多 3 列」。
- 持久化：选 2 列 → 刷新仍是 2 列（`localStorage.onefeed.feed.cols = "2"`）。
- 门禁：`pytest` 72 passed（含新增 5 条）；`node scripts/check-ui.mjs` 无违规；`npm run build` → `index-xKsQ_HKS.js` 445.04 kB / gzip 146.57 kB。

截图：`docs/images/2026-11-19-cols-{3,4,1,picker,narrow}.png`。

### 6.4 还没做的

- **左右侧栏本身没落地**（`docs/side-rails-2026-11-19.md` 仍是方案）。但它们落地时不需要再改这里：侧栏改变的是内容列宽度，`ResizeObserver` 会算出新列数并触发同一条 FLIP + 锚定路径。
- 设置页的「外观」节次入口（目前只有工具条 + Alt+数字）。
- 跨标签页 `storage` 事件同步列数（一个标签改了，另一个要刷新才跟上）。
- 侧栏 288↔64 的离散改宽动画（依赖侧栏实现）。

