# 动效库选型：侧栏平滑滚动 + 「稍后再看」弹出过渡

> 采集日期 2026-11-20。体积为 bundlephobia 的 min/gzip 字节，活跃度为 GitHub API 的 star 与 pushed 时间。所有结论都对着 onefeed 现有代码量过一遍，不是泛泛的「推荐清单」。

## 一、先诊断：两件事是两个病

用户的两句反馈要拆成两个不同的技术问题，混在一起选库一定选错。

### 1. 侧栏滚动「和想象不一样」

现状：`web/src/motion/useSmoothWheelScroll.ts` 是手写的 120 行方案——document 捕获阶段拦 wheel，命中 `[data-smooth-scroll]` 就累加目标位，再每帧按 `TAU_MS = 55` 指数逼近（`MIN_STEP = 0.4` 收尾），跳过 Mac 与 reduced-motion。

它的效果是「每一格都被拉长」，不是惯性：

- Windows 滚轮一格 `deltaY` 约 100，事件离散、没有速度信息可继承；
- 我们只做了「位置缓动」，没做「速度累积」，所以连滚三格只是三个独立缓动叠在一起，视觉上仍是嗒-嗒-嗒；
- 曲线写死在代码里，想调「更跟手」或「更绵」只能改常量重编译。

这是「自家实现缺一层惯性模型」，不是 bug。库的价值就在这里。

### 2. 「稍后再看」是瞬间弹出的

实测（Chrome 1600×900，pinned ≥1440，页内 rAF 采样）：

| 时刻 | aside 宽 | main 宽 | aside opacity |
| --- | --- | --- | --- |
| 打开前（t<190ms） | 不存在 | 1360 | — |
| t=254ms（出现那一帧） | **320** | **1040** | **0** |
| t=315ms | 320 | 1040 | 0.282 |
| t=496ms | 320 | 1040 | 1 |
| 关闭 t=1ms | 320 | 1040 | 1 |
| 关闭 t=14ms | **-1（已卸载）** | **1360** | — |

结论很硬：**布局位移完全没有动画**。320px 在同一帧里把内容列从 1360 挤到 1040，而唯一的进场动画 `rail-in` 只动 opacity 0.22s——肉眼看到的是「内容猛地一缩，然后一块半透明板子淡进来」。关闭更彻底：节点直接卸载，零退场。

代码依据：

- `web/src/layout/Shell.tsx:193-199`：pinned 时 `{rightOpen && <RightRail className="rail-in ... w-[320px] shrink-0" />}`，条件渲染 = 瞬时挂载/卸载。
- `web/src/theme.css:491-498`：`@keyframes rail-in { from{opacity:0} to{opacity:1} }`，注释写明「只动透明度，不动 transform —— 这一栏可能正好是 View Transition 的共享元素」。
- 对照窄屏抽屉 `web/src/layout/Shell.tsx:202-220`：`drawer-in` 0.24s `translateX(100%)→0`，那一条是真的滑入。桌面这一条是残废版。

所以第二件事**不需要库**，需要的是把宽度/位移纳入动画，并且让 `--shell-right-w` 这个给固定浮层用的 CSS 变量同步过渡。库里没有哪个能替我们决定「宽度动画还是覆盖式滑入」，那是个产品取舍。

## 二、候选对比

### 滚动类

| 库 | 版本 | min/gzip | deps | 活跃度 | 能否解决「不像惯性」 | 改造成本 | 结论 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| **lenis** | 1.3.27 | 18.9K / **5.5K** | 0 | 17.4k★，pushed 2026-11-19 | ✅ 速度累积 + lerp/duration 可调 + 多容器实例 | 低（换掉一个 hook，约 80 行） | **推荐** |
| overlayscrollbars | 2.17.1 | 30.9K / 15.1K | 0 | 5.2k★，2026-11-17 | ✅ 但附带自绘滚动条 | 高（Shadow DOM、滚动条样式与现有 CSS 打架） | 不采纳：我们不需要换滚动条 |
| gsap | 3.15.1 | 70.6K / 27.4K | 0 | 31k★，2026-11-04（license 字段 null） | ⚠️ 核心包不含平滑滚动（ScrollSmoother 在插件包），要自己接 | 高（双运行时 + 许可条款要核） | 不采纳：超配 |
| smooth-scrollbar | 8.8.4 | — | — | 3.3k★，**pushed 2023-06-06** | ✅ | 中 | 不采纳：停更 3.5 年 |
| 自研（现状） | — | 0 | 0 | 自己维护 | ❌ 缺速度模型 | — | 作为兜底保留思路 |

### 过渡 / 布局类

| 库 | 版本 | min/gzip | deps | 活跃度 | 对本项目的实际作用 | 结论 |
| --- | --- | --- | --- | --- | --- | --- |
| **motion（framer-motion）** | 项目现值 11.11.17 / 最新 14.14.0 | 140K / 46.0K（v11）→ 188K / 64.3K（v14） | 1→2 | 35.4k★，2026-11-19 | 已有：`AnimatePresence` + width/opacity 补间即可让右栏真过渡 | **用现成的，不新增** |
| @formkit/auto-animate | 0.10.2 | 8.8K / **3.5K** | 0 | 14.0k★，2026-11-07 | 列表项增删的 FLIP 动画，一行接入 | 可选，但会接管容器全部子节点动画，与现有 layout 冲突 → 不用 |
| vaul | 1.1.2 | 60.0K / 18.5K | 1 | 8.8k★，**pushed 2025-10-03**，163 issues | 移动端 bottom sheet + 手势 | 不采纳：停更 13 个月，形态也不对 |
| @radix-ui/react-dialog | 1.3.1 | 39.5K / 13.2K | **15** | 19.5k★，2026-10-14，300 issues | 只补 a11y 语义 | 不采纳：我们已有手写 dialog 原语（Confirm / AiDock / Lightbox） |
| react-spring | 10.0.4 | 52.1K / 20.0K | 6 | 29.3k★，2026-11-01 | 与 motion 完全重叠 | 不采纳：两套动画运行时是负债 |
| GSAP | 3.15.1 | 70.6K / 27.4K | 0 | 31k★ | 时间线编排很强 | 不采纳：为 260ms 的进出场引入 27KB 不划算 |

不升级 framer-motion 11 → motion 14 的理由：同源改名，gzip 从 46K 涨到 64K，对这两件事零收益。要升单独开一轮，不夹带在这次改动里。

## 三、推荐方案

### A. 滚动：换 Lenis，保留 `data-smooth-scroll` 作为标记

为什么它能解决「不一样」：Lenis 的模型是「速度 → 位置」，每次 wheel 把 `deltaY * wheelMultiplier` 加进目标速度，再按 `lerp` 逼近，松手后速度自然衰减。连滚三格得到的是三次加速，不是一个长缓动——这正是「惯性滚动」的手感来源。`lerp` 0.06~0.12 之间调「绵」，`wheelMultiplier` 1.0~1.4 调「跟手」。

集成骨架（替换 `web/src/motion/useSmoothWheelScroll.ts`）：

```ts
import Lenis from "lenis";

// 每个 [data-smooth-scroll] 容器一个实例；wrapper 就是该容器本身
function mount(el: HTMLElement) {
  const lenis = new Lenis({
    wrapper: el,
    content: (el.firstElementChild as HTMLElement) ?? el,
    lerp: 0.09,
    wheelMultiplier: 1.15,
    smoothWheel: true,
    syncTouch: false,
    autoRaf: true,      // 自带 rAF，不用我们接管
    autoResize: true,
    overscroll: false,  // 到边不要橡皮筋
    prevent: (node) => !!node.closest("[data-lenis-prevent]"),
  });
  return lenis;
}
```

要点与坑：

1. **作用域**：只给 6 个 `[data-smooth-scroll]` 容器挂（AgentSidebar 对话列表/图标轨、SavedList、SummaryList、FavoritesList、RightRail 同题列表、AgentThread），页面本体保持原生滚动。用户抱怨的是侧栏，不是整页。
2. **必须删掉旧的 CSS** `[data-smooth-scroll] { scroll-behavior: smooth }`（`web/src/theme.css`）。Lenis 自己写 `scrollTop`，配上 smooth 会让它每帧只挪一点——这个坑上一轮已经踩过一次（当时症状是滚三格共 24px）。
3. **嵌套滚动**用 `data-lenis-prevent` 显式标记，不要开 `allowNestedScroll`——README 明说它每次滚动都遍历 DOM，而我们侧栏里列表就套在可滚容器里。
4. **暂停**：AiDock / 灯箱 / Confirm 打开时调 `lenis.stop()`，关闭 `lenis.start()`，否则背景还能被滚。
5. **Mac 触控板**继续不接管。触控板本身已有系统级惯性，再叠一层 lerp 会变成「拖泥带水」。判断逻辑沿用现在 `/Mac|iPhone|iPad/` 的 UA 检测，只对 Windows 鼠标滚轮启用。
6. **reduced-motion**：不实例化，保持原生。

### B. 「稍后再看」：不引库，用已有的 motion 做真过渡

方案 A（推荐，先做）：宽度 + 透明度同步补间。

```tsx
// web/src/layout/Shell.tsx，pinned 分支
<AnimatePresence initial={false}>
  {railOpen && (
    <motion.div
      key="rail"
      initial={{ width: 0, opacity: 0 }}
      animate={{ width: 320, opacity: 1 }}
      exit={{ width: 0, opacity: 0 }}
      transition={{ duration: reduce ? 0 : 0.26, ease: [0.22, 1, 0.36, 1] }}
      className="sticky top-[57px] z-40 h-[calc(100vh-57px)] shrink-0 overflow-hidden border-l border-line"
      onAnimationStart={() => setRailW(0)}
      onUpdate={(latest) => setRailW(Number(latest.width))}
    >
      <RightRail defaultTab={...} onClose={dismissRail} />
    </motion.div>
  )}
</AnimatePresence>
```

同时 `--shell-right-w` 跟着 `railW` 走，让 AI 悬浮球 / ScrollTop 这类 `fixed` 浮层一起平移，而不是等动画结束才跳位。

风险：宽度动画会让 main 每帧 reflow。上一轮左栏宽度过渡被砍，根因是卡片字号跨 container-query 档位（已修，稳态 40–53ms）。右栏 320px 只会跨一次列数变化（4→3 列），预期可控；**实测如果单帧 >60ms 就切方案 B**。

方案 B（备选）：覆盖式滑入。aside 改成 `absolute right-0`，`translateX(24px)→0` + opacity，main 宽度不动。纯合成层、零 reflow，但会盖住最右一列卡片，和现在「两栏并存不遮挡」的约定冲突，只在 A 性能不过关时用。

关闭时同样要有 260ms 退场——`AnimatePresence` 天然保留节点到 exit 结束，这一条现在完全没有（t=14ms 就卸载了）。

## 四、预期效果与验收

| 项 | 现在 | 改后验收 |
| --- | --- | --- |
| 侧栏滚轮 | 一格一缓动，嗒-嗒-嗒 | 单次 wheel 产生 ≥12 帧运动，快起慢收；连滚 3 格不丢距离；1200px 用时 450–650ms |
| 到顶/到底 | 早退 | 不橡皮筋、不吞事件 |
| Mac / reduce | 不接管 | 保持不变 |
| 右栏开 | 一帧挤 320px + 0.22s 淡入 | 260ms 内宽度渐进（相邻帧变化 ≤40px），opacity 同曲线，浮层同步平移 |
| 右栏关 | 14ms 卸载 | 260ms 退场后再卸载，无「先消失再收窄」 |
| 帧预算 | — | 开/关全程单帧 <60ms，无 >150ms 长任务（复用 `probes/ops_frames.py`） |

## 五、落地顺序与成本

1. `npm i lenis`（5.5KB gzip），改写 `useSmoothWheelScroll.ts` → `useLenisContainers.ts`，挂载点不变，删掉 theme.css 里那条 smooth 规则。（约 1 小时）
2. 三个浮层写入 stop/start。（约 30 分钟）
3. Shell.tsx 右栏换 `AnimatePresence` + width 补间，`--shell-right-w` 跟随。（约 1 小时）
4. 补测试：`tests/test_motion_coverage.py` 钉住「lenis 已依赖」「无 scroll-behavior: smooth」「rail 用 AnimatePresence 且 duration 0.26」「reduce 下 0」。跑 `probes/ops_frames.py` 复测 `left.collapse` / `rail.open` / `rail.close`。（约 1 小时）
5. 实测若宽度动画超预算，切方案 B，只改 Shell 一处。

合计半天，无 API 破坏性变更，`data-smooth-scroll` 这个约定保留。

## 六、明确不做的

- 不引入 GSAP / react-spring / OverlayScrollbars / smooth-scrollbar / vaul / Radix，理由见上表。
- 不把整页滚动交给 Lenis（用户抱怨的是侧栏；整页接管会牵动 View Transition 与现有 `useScrollSpeedCap`）。
- 不升级 framer-motion 到 motion 14（+18KB gzip，与本次目标无关）。

## 七、实装结果（2026-11-20 下午）

方案 A 已落地：Lenis 接管侧栏、右栏宽度补间。差别在两处，都写在这里备案。

### 1. 滚动：Lenis 1.3.27，一个容器一个实例

`web/src/motion/useSmoothWheelScroll.ts` 整份重写（文件名与导出名不变）：

- `new Lenis({ wrapper: el, content: el, lerp: 0.09, wheelMultiplier: 1.15, smoothWheel: true, overscroll: false, autoRaf: true })`，每个 `[data-smooth-scroll]` 容器一个实例；**不接管 window**，页面本体仍由 `useScrollSpeedCap` 放行。
- 容器是后挂的（会话列表、右栏、线程），所以用 `MutationObserver` 增量接管；卸载的实例销毁。
- 追加行不改容器盒子尺寸，ResizeObserver 收不到，所以 DOM 一变就 `lenis.resize()`（120ms 去抖，避免流式输出时每帧扫全树）。
- Mac UA 与 `prefers-reduced-motion` 直接不装。
- `usePauseSidebarScroll(active)`：确认框（`ConfirmHost`）与灯箱打开时 `stop()`。Lenis 默认 `autoToggle: false`，stop 只停积分、不改容器 overflow，所以不会把滚动条弄没。
- theme.css 那条 `[data-smooth-scroll] { scroll-behavior: smooth }` **保留**：Lenis 用 `behavior: "instant"` 写位置，不会被 CSS 拖成每帧 2px；键盘 PageDown 仍然走这条平滑。

实测（1600×900，headless Chrome，页面内 rAF 采样）：

| 项 | 数据 |
| --- | --- |
| 左栏滚轮 3×400 | 119 帧、70 个不同位置、最大单步 32px、最大帧 16.7ms、0 帧 >60ms；行程累积到 568（容器到底） |
| 页面本体滚轮 500 | 60ms 时已在 160，最终 500 —— 一格走一格，没被 Lenis 接管 |
| 键盘 PageDown | 12 个不同位置、47 帧 —— CSS 平滑仍在 |
| 确认框打开时滚侧栏 | scrollTop 保持 0；Esc 后再滚到 560 —— 暂停生效 |

### 2. 右栏：宽度补间，但**不逐帧写根变量**

第一版在 motion 的 `onUpdate` 里把当前宽度写进 `--shell-right-w`，想让 AI 唤起器跟着栏一起挪。实测每帧 65–102ms，整段只有 6 个宽度档（一帧跳 231px），比不加动画还难看。

原因不在布局：受控微基准里，改一次 rail 宽度强制重排只要 5ms（卡片加 `content-visibility: auto` 后 0.4ms）。**慢在根元素上的自定义属性**——`:root` 的变量被整棵树继承，写一次就是一次全站样式重算。

改法：

- 变量只在开合那一刻写一次：`setProperty("--shell-right-w", (railOpen ? 320 : 0) + "px")`。
- 贴着内容列两侧的浮层（AI 唤起器三种形态、回顶部）加 `.shell-inset-x`，自己补 `left/right` 260ms —— 由 CSS 过渡接住变量的一次性变化，不再需要脚本逐帧写。
- 右栏外层 `motion.div` 只补 `width` + `opacity`，内层固定 `w-[320px]` 右对齐、父层 `overflow-hidden`：宽度从右缘向左长，栏里的标题不跟着横向滑动。
- 旧的 `.rail-in` 关键帧（只做 opacity）删掉 —— 它正是「一帧挤开内容区」的来源。

改后实测（同一台机器，开/关各 3 次）：

| 项 | 打开 | 关闭 |
| --- | --- | --- |
| 宽度档数 | 8–10 | 7–10 |
| 单帧最大 | 44.7 / 48.6 / 59.2ms | 36.7 / 41.1 / 82.8ms |
| p95 帧 | 33.7 / 47.7 / 51.0ms | 24.5 / 39.0 / 40.1ms |
| 有 >50ms 帧 | 0–2 | 0–1 |
| 结束后 | aside 在、变量 320px | aside 卸载、变量归 0 |

**没到 60fps，原因写清楚**：本机 headless Chrome 走软件光栅（SwiftShader），而这段动画每帧要重画 320px 宽、整列高的区域。真实 GPU 下应明显好于表中数字，但我没有在真机 GPU 上量过 —— 这项待用户在有显卡的浏览器里确认。

### 3. 顺带修的

- `Confirm.tsx`、`ItemPage` 灯箱：接 `usePauseSidebarScroll`。
- `tests/test_motion_coverage.py`：三条旧断言（`rail-in` 关键帧、`passive: false`/`capture: true` 的手写监听、旧右栏类名）改写成 Lenis 与宽度补间的语义，并新增 `test_right_rail_slides_open_with_a_width_tween`，把「不许逐帧写根变量」也钉进去。
- 门禁：`pytest` 112 passed、`check-ui` 无违规、`npm run build` 通过（index 513.09 kB / gzip 165.10 kB，Lenis 生产包约 19KB min）。

### 4. 还没做

- 左栏收展仍是瞬切（`.shell-col` 早就去掉了 width 过渡，因为逐帧重排太贵）。同样的道理，如果要做，应改成「内容列不动 + 左栏用 transform 滑」，而不是补宽度。
- 右栏在窄屏走抽屉（已有 `drawer-in`），本次没动。

