# 侧栏平滑滚动（2026-11-20）

## 现象

用户报「左右侧边栏仍然没有平滑滚动效果」：滚轮在左栏对话列表、右栏列表里都是一次跳一整段。

## 定位

1. 全站 grep `scroll-behavior`：只有 `web/src/theme.css` 的 reduce 块里一条 `auto !important`，**从来没有加过 smooth**。
2. 滚动容器清点（全部 `overflow-y-auto overscroll-contain`）：
   - `web/src/agent/AgentSidebar.tsx:135` 左栏对话列表、`:254` 图标轨
   - `web/src/components/SavedList.tsx:108`、`SummaryList.tsx:79`、`FavoritesList.tsx:97`、`RightRail.tsx:184`（同题列表）
   - `web/src/agent/AgentThread.tsx:26`（右栏 AI 页与底部 dock 共用）
3. 实测（Chrome 1600×900，左列表 scrollHeight 1100 / clientHeight 532，computed `scroll-behavior: auto`）：
   - 滚轮 `mouse.wheel(0, 400)` 的 scroll 轨迹：`[[2675, 400]]` —— **一个事件一步到位，中间零帧**。
   - 键盘 PageDown 的轨迹：`3 → 156 → 223 → 290 → 351 → 397 → 445 → 448` —— 键盘本来就是逐帧渐进。
4. 结论：**CSS 的 `scroll-behavior` 管不到滚轮**（规范上它只作用于键盘滚动与 scrollTo/scrollIntoView 这类 API）。
   Windows 的 Chrome 滚轮是阶梯式的，一次 wheel 直接把 scrollTop 推到位，所以只补 CSS 修不好。
   `motion/useScrollSpeedCap.ts` 也不是元凶：它的 `ownsScroll()` 会让所有可滚容器内部的事件直接放行。

## 修法

- 新增 `web/src/motion/useSmoothWheelScroll.ts`：document 捕获阶段监听 wheel，只接管带 `data-smooth-scroll` 的最近容器；
  把轮子位移累加进目标位，每帧按指数缓动追赶（时间常数 55ms，约 300ms 收尾）。
  - 不接管：Ctrl/⌘+滚轮（缩放）、横向滚动、已到顶/到底（交回外层，页面还能滚）、prefers-reduced-motion、macOS/iOS（原生已有惯性）。
  - 因为用的是捕获阶段，它先于 `useScrollSpeedCap` 的 window 监听执行；一旦 preventDefault，限速那层看到 `defaultPrevented` 就跳过，不会双重接管。
- 六个侧栏列表补 `data-smooth-scroll`；`theme.css` 给它们加 `scroll-behavior: smooth`，让键盘翻页、程序化滚动同样平滑（reduce 块里的 `auto !important` 会覆盖回去）。
- **踩到的坑**：容器上有 `scroll-behavior: smooth` 之后，每帧直接赋 `scrollTop` 会被浏览器当成一次平滑滚动 —— 缓动和浏览器抢方向盘，实测每帧只挪 2px，滚 3 格才走 24px。改成 `scrollTo({ behavior: "instant" })` 后正常。
  同理 `web/src/agent/AgentThread.tsx` 的自动吸底也改成 instant，避免流式刷新时追不上最新一行。

## 验证（Playwright + CDP，1600×900）

| 场景 | 修前 | 修后 |
| --- | --- | --- |
| 左栏滚轮 400×3 | 单步 400，零中间帧 | 30 帧：101 → 165 → 216 → … → 560（settled 567，到底） |
| 右栏滚轮 400×3 | 单步（列表不可滚时无事件） | 44 帧：101 → 165 → … → 868 → … → 1198（= 3×400 累加） |
| 键盘 PageDown | 逐帧（原生） | 仍逐帧：12 → 39 → 82 → … → 448 |
| prefers-reduced-motion | — | 不接管：单步 400，computed `scroll-behavior: auto` |
| 页面本体滚轮 | 500 | 仍 500（侧栏缓动没抢页面） |

门禁：`pytest` 111 passed（新增 `tests/test_motion_coverage.py::test_sidebars_ease_wheel_scrolling`）、`node scripts/check-ui.mjs` 无违规、`npm run build` 通过。

## 未做

- 触屏/移动端没测（本地桌面应用）。
- `AgentHistory` 的 dense 历史下拉没挂缓动（高度只有 42vh 且条目少）。
