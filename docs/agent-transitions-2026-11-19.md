# Agent 三形态之间的转场（2026-11-19）

用户提出的两条：

1. 从 Agent 对话框里打开视频，要像信息流那样带缩放：对话框平滑移到右侧变成右栏，视频从右侧放大出来；退出反向还原。
2. AI 助手的唤起器原来贴在屏幕右下角，但页面内容居中 1180px，两侧空着；而且打开没有动画，要一个缩放。

## 做法：一个常驻名字 + 一个代位盒子

三形态（唤起器 / 底部抽屉 / 右侧栏）本质是同一块面板换壳，所以只用一个 view-transition-name：`of-agent`。

- 抽屉的名字挂在**内层 760 宽面板**上（web/src/agent/AgentSurface.tsx），不是外层 `fixed inset-x-0` 通栏容器 —— 挂外层会让新快照的插值盒子横向铺满整屏。
- 右栏的名字挂在 `aside`（web/src/agent/AgentRail.tsx）。
- 唤起器不常驻名字：它只在「收起后」出现，用代位盒子（web/src/motion/ghost.ts）在快照里补一个同尺寸的盒子，浏览器就能把它与抽屉插值起来。

代位盒子模块提供三样东西：`contentEdges()`（按 1180 / 24px gutter 算内容栏），`launcherBox("pill"|"corner")`（唤起器两形态的几何），`createGhost({media,title,agent})`（按需在右沿造 `of-media` / `of-title` / `of-agent` 的占位元素）。

方向语义沿用 `runNav` 的 kind：

| 动作 | kind | 效果 |
| --- | --- | --- |
| 唤起器 → 抽屉 | `tab` | 旧侧隐藏、新侧入场（从唤起器位置长出来） |
| 抽屉/右栏 → 唤起器 | `back` | 旧侧可见收缩、新侧隐藏 |
| 抽屉 → 右栏（打开一条内容） | `push` | 面板平移同时视频从右侧放大 |
| 右栏 → 抽屉（返回信息流） | `back` | hero 缩回右侧、面板退回抽屉 |

## 从对话打开一条：两条路径合成一条

原来 Agent 自己打开条目走的是 `applyUi` 里的一句裸 `navigate`，压根没进 View Transition。现在 `ui_open_item` 调 `openItem(id, seed)`，和点卡片是同一条路：

1. 页面上有这张卡 → 用卡里的 `[data-vt="media"]` / `[data-vt="title"]` 当名字；
2. 没有（Agent 自己找出来的条目）→ 补右侧代位盒子；
3. `seed` 从这一轮结果（`turnsRef`）里取，作为详情页首屏数据 —— 没有它新页面先渲染骨架，骨架里没有媒体框，共享元素少一半，转场会退回整页淡出。

## 踩到的坑

- **同名重复会让浏览器整段跳过转场**。第一版把旧快照用的代位盒子留到动画结束才摘，新快照里 ghost 与真面板都有 `of-agent`，控制台报 `Unexpected duplicate view-transition-name: of-agent`，表现为「打开毫无动画」。修法：`apply` 的第一件事就 `ghost.remove()`（此时旧快照已拍完）。
- **收起方向的盒子要挂进 apply 内**：唤起器是收起之后才渲染的，旧快照里没有它，盒子只有放进 apply（新快照）才是终点。
- **从 Agent 返回信息流时不能给卡片挂名字**：`FeedPage` 的 `backId` 锚定会让卡片和右侧盒子同名，同样整段作废。加 `backFromAgent` 抑制。

## 唤起器对齐

两形态都改成「外层 `fixed inset-x-0` + 内层 `mx-auto max-w-[1180px] px-6`」：

- 信息流：胶囊 `min(760, 内容宽)` 居中于内容栏；
- 详情页：圆钮 104×44，贴内容栏右沿，`bottom: 20`。

## 验证（playwright + channel chrome，1280×860 / 900×800）

- 唤起器对齐：main `x50 w1180 right1230`；胶囊 `x260 w760 right1020`；圆钮 `x1127 y796 w103 right1230`。900 宽时圆钮 right=876（= 900-24），打开走抽屉而非右栏。
- 打开抽屉：`of-agent` 760×48 @ (260,796) → 760×200 @ (255,584)，从唤起器位置往上长；无 duplicate 报错。
- Agent 自开条目（真模型，5.7s）：旧 代位盒子 `of-media 320×180 @ (886,584)`、`of-title 320×44 @ (886,530)` → 新 hero `720×405 @ (69,273)`、`720×35 @ (69,119)`，同时 `of-agent` 变 380×764 @ (821,81) 的右栏。
- 返回：`back` +120ms 新快照 ghost 里是右侧的 media/title，旧快照是 hero → 缩回右侧；`of-agent` 从 380×764 退回 760×533 抽屉。
- `prefers-reduced-motion`：抽屉正常打开、无残留 `vt-running` 类、无 console 错误。
- 门禁：`pytest` 66 passed；`node scripts/check-ui.mjs` 无违规；`npm run build` → `index-BUcx1t5o.js` 438.47 kB / gzip 144.47 kB。

## 回归

tests/test_interaction.py`::test_agent_surface_transitions` 守六件事：ghost 模块存在且按 1180 算内容栏、抽屉名字挂内层、唤起器对齐、三种 kind 都在用、`ui_open_item` 不许裸 navigate、`ItemPage` / `FeedPage` 的 fromAgent 分支。

## 未做

- 窄屏真机只有 900×800 一档；
- 抽屉与右栏之间宽度 380↔760 是直接插值，不是两段动画；
- Safari 的 View Transition 支持尚未验证。
