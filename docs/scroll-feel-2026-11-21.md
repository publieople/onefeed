# 滚轮手感：从「黏」到「跟手」（2026-11-21）

> **后续（2026-11-21 下午）**：用户仍觉得这一版「跳变式」——当帧走掉 62%（一格 71px）本身就是可见的一跳。做九宫格对照页后改回 Lenis 调校档（duration 0.85 + easeOutQuart），见 [scroll-lenis-2026-11-21.md](scroll-lenis-2026-11-21.md)。本文保留作为那一步的推导记录。

用户两次说滚动不满意（2026-11-20「和我想象的滑动效果不一样」、2026-11-21「现在这个滚动效果我也不满意，找找有没有更丝滑跟手的实现」）。第一轮换了 Lenis，第二轮把 Lenis 也拿掉，改成自研的两段式引擎。

## 一、先说病因（逐帧实测，Chrome headless 1440×900）

在页面里装 rAF 采样器，记录每次 `scrollTop` 变化的时间与步进。

| 场景 | Lenis 版（lerp 0.09） | 现在 |
| --- | --- | --- |
| 侧栏 1 格滚轮 | 首像素 +40ms，首帧只走 8px，43 个变化帧，**841ms** 才停在 114 | 首像素 +13ms，首帧走 **71px**，16 个变化帧，**267ms** 停在 115 |
| 页面 1 格滚轮 | 5 个变化帧，32px 一跳，**没有缓动** | 首帧 71px，16 个变化帧，266ms 停稳到 115 |
| 侧栏 3×400 | 事件当帧一步跳 288px，再磨到 4512ms 才到底 | 每格当帧 285px（跟手），到边后这一格顺着链交给页面滚 |
| 页面 3×400 | 含 154px / 96px 两处掉帧大跳 | 单帧最大 80px；6×100 连滚总量 690，**一格不丢** |
| 触控板式 10×20 | — | 51 帧，单帧最大 18px，总量 230 精确 |

两个病的本质：

1. **Lenis 是纯位置缓动**：lerp 0.09 意味着事件当帧一步都不走，要 300–400ms 才把这一格走完，尾巴拖到 800ms+。手感是「黏着往前爬」，不是「滑」。
2. **页面本体当时是另一套**：`useScrollSpeedCap` 只做「每帧放行 N 像素」的匀速限制，没有惯性也没有余速，Windows 一格 100px 就是 32/64/96/100 的阶梯。

## 二、改成什么

一个新的 `web/src/motion/useSmoothWheelScroll.ts`，两段式：

- **当帧跟手**：滚轮事件里直接把 `delta × 1.15 × 0.62` 写进 `scrollTop`，眼睛立刻有反馈。
- **余量滑行**：剩下的差额按时间常数 55ms 指数收尾（280ms 内停住），所以还有一点余速，但不拖尾。
- **每帧上限**：单帧位移不超过 `2000 × dt`（dt 上限 32ms → 单帧最多 64px）。掉帧时不至于一帧跳 150px。
- **漂移保护**：每帧先读一次真实位置，若与引擎记录差 >2px（路由切换的 `scrollTo(0)`、键盘翻页、`scrollIntoView`），以真实位置为准，不拿旧 target 把人拽回去。实测：滚到 800 → 点卡片进详情，`scrollY` 停在 0 且 800ms 后仍是 0。
- **页面与侧栏共用一套**：删掉 `useScrollSpeedCap.ts`，页面本体也走这个引擎；侧栏滚到顶/到底时，这一格顺着滚动链交给页面（同一个引擎滚），不再 handOff 给浏览器让两套缓动打架。

参数（都在文件顶部，改一个数就能调）：

```ts
const IMMEDIATE = 0.62;        // 一格滚轮当帧走掉的比例
const TAU_MS = 55;             // 余量收尾的时间常数
const WHEEL_MULTIPLIER = 1.15; // Windows 一格 100px 略放大
const MAX_SPEED = 2000;        // 每帧上限 = MAX_SPEED × dt
const MAX_DT = 0.032;          // 单帧最多按 32ms 算
const IDLE_FRAMES = 6;         // 空闲 6 帧就停 rAF
const EPSILON = 0.4;           // 余量小于它直接对齐
```

## 三、保留的边界（没有一律接管）

- **Mac / iOS 不接管**：触控板自带惯性，再套一层会滑过头。
- **prefers-reduced-motion 不接管**：实测一格滚轮就是原生的一步 0→100，只有 2 个采样点。
- **Ctrl/⌘ + 滚轮**（缩放）、**横向滚轮**直接放行。
- **其它自有滚动容器**（评论列表等）通过 `ownsScroll` 交回浏览器。
- **模态层**（确认框、灯箱、帮助层）打开时 `isPageScrollLocked()` 吞掉滚轮，计数式 `pauseDepth` 保证嵌套模态先关的不会解掉后关的暂停。实测确认框打开时滚 600，`scrollY` 纹丝不动。
- 容器上的 `scroll-behavior: smooth` 保留给键盘翻页；引擎写位置时显式 `behavior: "instant"`，否则会被浏览器拖成每帧 2px（上一轮踩过：滚三格只走 24px）。

## 四、代价

- 删掉 Lenis 依赖，主包 **451.58 kB → 430.52 kB**（gzip 143.88 → 137.60）。
- 空闲时 rAF 挂起（连续 6 帧没人动就 `cancelAnimationFrame`），与上一轮的结论一致：不滚就不耗。
- 逐帧写 `scrollTop` 本身会触发布局，但只在动画期间发生，量级与浏览器原生滚动同级。

## 五、改了哪些文件

- `web/src/motion/useSmoothWheelScroll.ts`：整份重写（不再依赖 Lenis）。
- `web/src/motion/useScrollSpeedCap.ts`：删除（页面限速合并进新引擎）。
- `web/src/App.tsx`：只留 `useSmoothWheelScroll()`。
- `web/src/agent/AgentThread.tsx`、`web/src/theme.css`：注释改为「缓动引擎」，去掉 Lenis 的说法。
- `web/package.json` / `package-lock.json`：移除 `lenis`。
- `tests/test_motion_coverage.py`、`tests/test_infinite_and_rail.py`：钉住新引擎的常量、当帧跟手、每帧上限、边界转页面、漂移保护、无 Lenis。
- `probes/probe_scroll_feel.py`（逐帧手感）、`probes/probe_scroll_guards.py`（触控板 / 路由 / 模态锁）、`probes/probe_scroll_reduce.py`。

## 六、验收

`pwsh scripts/preflight.ps1` 全绿（pytest 116 passed、26 项离线用例、check-ui 无违规、build 通过）。

手感的最终裁判是真机滚轮。如果上机觉得「还是有点飘」，把 `TAU_MS` 调到 40；觉得「一格走太远」，把 `WHEEL_MULTIPLIER` 降到 1.0；觉得「起手不够狠」，把 `IMMEDIATE` 提到 0.75。
