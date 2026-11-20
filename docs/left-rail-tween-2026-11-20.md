# 左栏也走宽度补间（2026-11-20 晚）

## 为什么改

用户原话：「左侧栏动效也改成右侧栏那种滑入滑出的效果」。

此前两栏手感是分开的：

- 右栏：`Shell` 里的 `motion.div` 补宽度 0→320 + opacity，内层固定 320 右对齐，宽度从右缘向左长。
- 左栏：`.shell-col { transition: none }` 硬切 240↔64，靠中间列 200ms 位移+淡入（`content-settle-*`）「接住」这一下。

硬切是当时用帧数据换来的决定（逐帧改内容列宽会让 30 张卡全部重排，见 `docs/perf-fixes-2026-11-20.md`）。但两栏一个滑一个跳，用户能看出来。

## 改了什么

- `web/src/layout/Shell.tsx`：左栏从 `<div style={{width:leftW}}>` 换成 `motion.div`：
  `initial={false}` / `animate={{ width: leftW }}` / `transition={reduce ? {duration:0} : {duration: DUR.page, ease: EASE}}`。
  内层 `AgentSidebar` 仍是两层常驻、各自定宽（展开层 240 / 图标轨 64），被窄列裁掉 —— 不会先按 64px 重排再展开。
- 删掉 `settle` state/effect 与 `<main>` 上的 `content-settle-*` 类。那是「换宽一步到位」的补丁，宽度开始补间之后再叠一层位移淡入会抖两次。
- `web/src/theme.css`：删 `content-settle-expand/-collapse` 关键帧与类；保留 `.shell-col { transition: none }` 并改注释——宽度是逐帧 inline style，若再有 CSS 过渡，浏览器会再补一遍，两层动画打架；reduce 块只剩 `.side-layer`。
- `tests/test_motion_coverage.py`：原来钉住「列宽必须没有过渡」的断言，改成钉住 motion 补间的四个特征（`motion.div` / `initial={false}` / `animate={{ width: leftW }}` / `DUR.page`），并断言 `content-settle` 在源码里彻底消失。

## 实测（Chrome headless 1440×900，961 条真实数据）

宽度确实是分档补间，不是跳变：

- 收起：240 → 142.5 → 96.8 → 80.3 → 71.2 → 66.1 → 64.5 → 64（9–10 档）
- 展开：64 → 101.8 → 206.3 → 227.3 → 234.9 → 238.2 → 239.5 → 240

帧耗时（轻量采样，采样器只读列宽，不碰 `getComputedStyle`，长任务用 PerformanceObserver）：

| 操作 | p95 帧 | 最大帧 | 长任务 |
| --- | --- | --- | --- |
| left.collapse 240→64 | 47ms | 134ms | 首次 127ms；第 2、3 轮 0 |
| left.expand 64→240 | 27ms | 40ms | 0 |
| 对照：right.close 320→0 | 39ms | 53ms | 50ms |

- 首次那条 127ms 是冷启动（第一次按目标列宽排版 + 图标轨首次绘制），之后同一会话不再复现。
- 卡片 `display:none` 对照：13–27ms/帧 → 剩余成本来自 30 张卡随列宽流失，符合预期。
- reduce：`[240, 240, 64, 64, …]`，一帧完成。
- 层可见性：收起后 full `opacity 0 / visibility hidden`、rail 透明 1 且 `elementFromPoint` 命中图标轨按钮；展开反之。`--shell-left-w` 240→64，底部 AI 唤起器 left 460→372 跟随（`shell-inset-x` 260ms 补间）。

## 代价与边界

- **逐帧回流**是补宽度的固有成本。上一版就是因为这个（26.8fps / 241ms 长任务）才改硬切；现在卡片字号是分档 `@container`（250/600），宽度变化不再跨字号档，稳态 13–40ms/帧，与右栏同一量级，因此可以接受。headless 走 SwiftShader 软件光栅，真机 GPU 应更好。
- 没上 `content-visibility`：能再压一半，但屏外卡片按估算高度占位，滚动落点会漂，和「反感整页位移」冲突，不做。
- 交叉淡入：两层叠在同一列上，收放时约 60–100ms 双可见（硬切时看不到）。属既有 `.side-layer` 设计，本次未改时长。
- 未测：Safari / Firefox；窄屏（<960 两栏都不渲染）。

## 验证

- `uv run --with pytest python -m pytest tests -q` → 112 passed
- `cd web; node scripts/check-ui.mjs` → 无违规
- `cd web; npm run build` → `dist/assets/index-CR-UP0mD.js` 512.63 kB / gzip 164.98 kB、`index-ZHeiViwZ.css` 50.53 kB
- 探针：`probes/probe_left_tween.py`、`probe_left_tween2.py`、`probe_left_repeat.py`、`probe_left_states.py`、`probe_left_reduce.py`
- 截图：`docs/images/2026-11-20-left-expanded.png`、`docs/images/2026-11-20-left-collapsed.png`
