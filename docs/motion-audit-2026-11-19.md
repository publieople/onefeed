# 交互动效审计（2026-11-19）

## 0. 一句话

左右栏「动画又没了」不是逻辑坏了，是动画依赖的三样东西被这轮结构改动挤掉了；
顺手把全站 36 个交互点按「悬停 / 按下 / 聚焦 / 出现 / 收起 / 状态切换」六类扫了一遍，
补了 12 处，并把「进场动画不能靠两帧时序」这条钉进了守门测试。

## 1. 怎么查的

- **源码逐个过**：把每个交互点拆成六类（hover / active / focus / enter / exit / state-change），在组件里找对应 class、`motion.*`、CSS keyframes。
- **运行时确认**：Playwright + `channel=chrome`，1280×860，服务 `http://127.0.0.1:8799`（924 条真实数据）。
  - 动画有没有跑：`el.getAnimations()` 读 `animationName` / `transitionProperty` / `duration` / `playState`。
  - 中间帧有没有：采样器**装进页面**用 rAF 逐帧记几何，**先开始录、再触发交互**。
- **一个测量陷阱（差点误判）**：从 Python 侧 `page.evaluate` 轮询往返要 200ms 以上，320ms 的过渡采到的全是终态，看起来就像「瞬间跳」。
  改成页内 rAF 之后，左栏展开实测 `64 → 110 → 250 → 273 → 288`（约 330ms），收起 `288 → 242 → 209 → 161 → 114 → 93 → 79 → 67 → 64`（约 250ms）。

## 2. 三个根因

1. **「先渲染收起态、下一拍再切展开态」这招不可靠。**
   主线程一忙（首屏、批量解码），两次 `setState` 会被合并成一帧提交，元素**一出生就是终态**，
   浏览器根本没有「before-change style」，过渡不会跑。抽屉、底部抽屉当时就是这么变成硬切的。
   现在：进场一律交给 CSS `@keyframes`（`animation` 随元素创建自动开始，不依赖任何时序），
   收起才用 `transition` + `setTimeout` 卸载。
2. **带逗号的 arbitrary 类在产物 CSS 里根本没有生成规则。**
   `transition-[transform,opacity]` 编译成空，实测 `transition-property: none`，
   属性切了但没有过渡。改成内置 `transition`（属性表本就含 transform / opacity）后立刻正常。
   `transition-[width]`、`transition-[padding-right]` 这种单属性 arbitrary 是好的，可以继续用。
3. **`animation-fill-mode: both` 的进场动画会永久压住 `transform`。**
   上一轮换列 FLIP 失效就是这个：`.rise` 的 `both` 让 `transform: translate3d(0,0,0)` 常驻，
   CSS 动画优先级高于行内样式，framer 写的 transform 被覆盖成 0。
   本轮新的 `sheet-in` / `drawer-in` 一律用 `backwards`：开播前应用首帧，结束后不填，
   收起时的 `transition` 才抢得到 `transform`。

## 3. 逐项检查表

状态：**✓ 本来就有** / **＋ 本轮补** / **– 有意不做**。

| # | 交互点 | 之前 | 现在 |
|---|---|---|---|
| 1 | 左栏展开 64→288 | 两个组件分支直接替换，宽度瞬跳 | ＋ 同一容器宽度过渡 220ms（`Shell.tsx:92`） |
| 2 | 左栏收起 288→64 | 同上 | ＋ 同上，内容列同步变宽 |
| 3 | 左栏图标轨 hover | ✓ 有背景过渡 | ✓ |
| 4 | 右抽屉滑入（1280–1799） | `fixed` 直接出现 | ＋ `drawer-in` 关键帧 240ms（`Shell.tsx:120`） |
| 5 | 右抽屉滑出 | 直接卸载 | ＋ `translate-x-full` 过渡 + 240ms 后卸载 |
| 6 | 右栏让位（打开时内容列变窄） | padding 瞬间跳 364px | ＋ `transition-[padding-right]` 240ms（`Shell.tsx:85`） |
| 7 | 右栏让位回退 | 关闭瞬间跳回 | ＋ 同上（实测 364 → 40.7 → 20） |
| 8 | 常驻右栏出现（≥1800） | 直接出现 | ＋ `rail-in` 淡入（`theme.css:457`） |
| 9 | 右栏 tab 切换（稍后再看 / AI / 同题） | 内容硬换 | ＋ 按 tab 键淡入 4px（`RightRail.tsx:129`） |
| 10 | 右栏收起的两种语义（收起 AI vs 收起右栏） | ✓ 行为正确 | ✓ |
| 11 | 底部抽屉出现 | 直接出现（`if (!open) return null`） | ＋ `sheet-in` 关键帧 220ms（`AgentSurface.tsx:163`） |
| 12 | 底部抽屉收起 | 直接消失 | ＋ `translate-y-6 opacity-0` 过渡 + 220ms 后卸载 |
| 13 | 唤起器出现/收起（滚动感应） | ✓ translate-y + opacity 300ms | ✓ |
| 14 | 唤起器 hover / 聚焦钉住 | ✓ | ✓ |
| 15 | 回到顶部按钮 | ✓ translate + opacity | ＋ 加 `scale`（90%↔100%，`ScrollTop.tsx:33`） |
| 16 | 信息流「正在获取新内容…」 | 文案硬切 | ＋ 按状态 key 淡入上移（`FeedPage.tsx:489`） |
| 17 | 无限加载追加卡片 | ✓ `.rise` 进场 340ms | ✓ |
| 18 | 换列重排 | ✓ FLIP（`layout="position"` + 文档坐标锚定） | ✓ |
| 19 | 卡片 hover / 按下 / 聚焦环 | ✓ y-2 / scale .985 / ring | ✓ |
| 20 | 卡片进详情（共享元素） | ✓ of-media / of-title 0.42s | ✓ |
| 21 | 平台胶囊选中滑块 | ✓ layoutId 弹簧 | ✓ |
| 22 | 平台胶囊方向键 | ✓ 只挪焦点 + 自动滚入视野 | ✓ |
| 23 | 排序 / 时间 Seg | ✓ 滑块 | ✓ |
| 24 | 每行卡片数弹层 | ✓ 淡入 + 上移 | ✓ |
| 25 | 已收藏 / 稍后再看 / 每行卡片数按钮 | ✓ hover + aria-pressed | ✓ |
| 26 | 详情页 AI 总结 / 原文 切换 | 内容硬换 | ＋ 两个 tab 各自 `rise` 入场（`ItemPage.tsx:1030` / `:1051`） |
| 27 | 详情页灯箱开/合 | ✓ of-lb 共享元素 | ✓ |
| 28 | 详情页 AI 流式 | ✓ 逐字 + 光标 | ✓ |
| 29 | 评论「查看更多」 | 新条目直接出现 | – 列表体量大，逐条入场会闪；留给后续按需补 |
| 30 | Agent 轨迹每来一步 | 直接插入 | ＋ `fade-in`（`AgentConsole.tsx:99/103/108`） |
| 31 | Agent 结果卡收藏星标 | 只有颜色变化 | ＋ `active:scale-90`（`AgentThread.tsx:219`） |
| 32 | Agent 历史展开 | 硬出现 | ＋ `rise`（`AgentHistory.tsx:10`） |
| 33 | 稍后再看：移出 | 瞬间消失 | ＋ 左移淡出 160ms 后移除（`SavedList.tsx:116`） |
| 34 | 稍后再看：撤销条 | 硬出现 | ＋ `rise` |
| 35 | 设置页开关 / 插件开关 | ✓ 滑块位移过渡 | ✓ |
| 36 | 设置页「有未保存的改动」条 | ✓ motion 入场/退场 | ✓ |
| 37 | 市场页提示条（安装/卸载/撤销） | 硬出现 | ＋ `rise`（`MarketPage.tsx:263`） |
| 38 | 确认弹窗 / 快捷键表 / 全局 toast / 主题切换 | ✓ 均有入场动画 | ✓ |
| 39 | 系统「减少动态效果」 | 部分遗漏 | ＋ 统一 `@media (prefers-reduced-motion: reduce)`（`theme.css:467`） |
| 40 | 侧栏会话项 hover / 当前项高亮 | ✓ 颜色过渡，无位移动画 | ✓（– 不做位移，列表里会吵） |

## 4. 本轮改动清单

| 文件 | 改了什么 |
|---|---|
| `web/src/motion/usePresence.ts`（新） | `{ mounted, shown }`：出现即时挂载（进场交给 CSS），收起 `setTimeout` 后卸载。不用 AnimatePresence / rAF 收尾 |
| `web/src/layout/Shell.tsx` | 左栏单一容器按 `shell.left` 出宽度（288/64）+ `min-w-0`；右抽屉 `drawer-in` + `translate-x-full`；外壳 `transition-[padding-right]` |
| `web/src/agent/AgentSidebar.tsx` | 两段宽度归外层，内层固定 288，展开是「滑出来」不是被压扁 |
| `web/src/agent/AgentSurface.tsx` | `AgentSheet({ shown, named })`：不再 `if (!open) return null`，加 `sheet-in` + 收起过渡 |
| `web/src/theme.css` | `@keyframes sheet-in / drawer-in / rail-in` + `backwards` 填充 + reduce 覆盖 |
| `web/src/components/RightRail.tsx` | tab 内容 `motion.div key={tab}` 淡入 4px |
| `web/src/pages/FeedPage.tsx` | 底部状态条按 loading 状态 key 淡入 |
| `web/src/components/SavedList.tsx` | 移出先 `leaving` 左移淡出 160ms 再删；撤销条 `rise` |
| `web/src/components/ScrollTop.tsx` | 收起态加 `scale-90` |
| `web/src/components/AgentConsole.tsx` | 轨迹行 `fade-in` |
| `web/src/agent/AgentThread.tsx` | 收藏星标 `active:scale-90` |
| `web/src/agent/AgentHistory.tsx` | 根节点 `rise` |
| `web/src/pages/ItemPage.tsx` | 两个 tab 的内容各包一层 `rise` |
| `web/src/pages/MarketPage.tsx` | 提示条 `rise` |
| `tests/test_motion_coverage.py`（新） | 7 条守门，见第 6 节 |

## 5. 实测数字

1280×860，Chrome，`channel=chrome`，服务 8799：

| 场景 | 证据 |
|---|---|
| 左栏展开 | 页内 rAF：64 → 110 → 250 → 273 → 288（约 330ms） |
| 左栏收起 | 288 → 242 → 209 → 161 → 114 → 93 → 79 → 67 → 64（约 250ms） |
| 右抽屉打开 | `getAnimations() = [{name:"drawer-in", state:"running", dur:240}]`；逐帧 940 → 1005 → 1052 → 1090 → 1122 → … |
| 右抽屉关闭 | `[{name:"opacity",dur:240},{name:"transform",dur:240}]`，之后节点卸载 |
| 右栏让位 | padding-right 364 → 40.7 → 20 |
| 底部抽屉打开 | `[{name:"sheet-in", state:"running", dur:220}]` |
| 底部抽屉关闭 | `[{name:"opacity",dur:220},{name:"transform",dur:220}]`，220ms 后卸载，唤起器回来 |
| 详情页 tab 切换 | `.rise` 的 `rise` 动画 state=running（切「原文」后 60ms 采样） |
| 减少动态效果 | `getAnimations()` 空、`transitionDuration: 1e-06s`，节点正常出现与卸载 |
| 控制台 | 0 error |

## 6. 门禁

`tests/test_motion_coverage.py` 7 条，把「动效依赖的东西」钉住而不是钉具体像素：

1. `usePresence` 不靠第二次渲染（有 `mounted`/`shown`/`setTimeout`，不引 framer-motion、不用 rAF）。
2. 左栏宽度在自己那一列过渡，且有 `min-w-0`（否则 flex item 被 min-content 撑死）。
3. 右抽屉 `drawer-in` 进场 + `translate-x-full` 退场 + 让位 padding 也过渡。
4. 底部抽屉保持挂载退场（`shown`/`named`/`sheet-in`），退场期间不把唤起器塞回来。
5. `sheet-in / drawer-in / rail-in` 三个 keyframes + `backwards` + reduce 覆盖都在。
6. 每个「弹出来」的表面都有入场：确认弹窗、快捷键表、每行卡片数、右栏 tab、市场提示条、详情页两个 tab、Agent 轨迹、收藏星标。
7. 状态类反馈：信息流状态条按 key 淡入、稍后再看左移淡出、回到顶部缩放。

```
uv run --with pytest python -m pytest tests -q        → 94 passed
cd web; node scripts/check-ui.mjs                     → OK：没有违规
cd web; npm run build                                 → index-7qSYc8km.js 469.16 kB / gzip 152.99 kB
```

## 7. 未做 / 有意不做

- **评论「查看更多」的逐条入场**：一次插入 20 条，逐条动画反而闪；要做得配虚拟列表。
- **侧栏会话项的位移动画**：列表里做位移会让滚动中的文字抖，只保留颜色过渡。
- **抽屉可拖拽关闭**：手指拖动跟 `drawer-in` 关键帧会打架，需要改成全程 JS 驱动，单独一轮做。
- **窄屏真机**：只验了 1280 与 900 两档；iOS Safari 的 `view-transition` 与 `backdrop` 未验。
- **触屏没有「指针贴边」**：唤起器的 reveal 依赖 `pointermove`，手机上只能靠上滑（`scroll` 方向）。

## 8. 补记（2026-11-19 20:10）：侧栏底部三行「发灰」不是颜色，是底部渐隐层盖上去的

用户截图（342×142）里「稍后再看 0 / 快捷键 ? / 设置」三行依次变淡、像被禁用。查下来颜色 token 一直没变：

- 三行的 computed `color` 全是 `rgb(107, 114, 128)`（`--c-muted`）、12px、祖先链 `opacity` 无衰减、无 `filter`/`mask`、无动画残留 → 文字本身没问题。
- 拿 canvas 采样用户截图：y≈32 行最深像素 ≈(115,122,135)、y≈64 行 ≈(184,188,194)、y≈96–112 行 ≈(225,226,226) → 按垂直位置递减，是渐变刷淡。
- 根子在 `web/src/agent/AgentSurface.tsx:78-81`：底色渐隐 `pointer-events-none absolute inset-x-0 bottom-0 h-28 bg-gradient-to-t from-paper` 挂在一个 `fixed inset-x-0 bottom-0 z-30` 的包裹上，横跨整个视口；左栏 `h-[calc(100vh-96px)]` 底边就在 y≈100vh-20，三行 y=781/811/841（视口 900）全落在最后 112px 的渐变带里。

修法是 z 序，不是算列宽：两栏都是不透明纸色底（`bg-paper`），抬到渐隐层之上，渐变就只留在内容区。

- `web/src/layout/Shell.tsx` 左列加 `z-40`，pinned 右栏 `rail-in sticky ... z-40`。
- 复验（1440×900，Chrome）：`shot-footer-fixed.png` 三行回到实色 muted；`shot-veil-content.png` 内容区底部渐隐仍在（卡片照样淡进纸面）；`shot-rail-bottom.png`（1800 宽）右栏底部纯净无着色；暗色 `shot-footer-dark.png` 三行等浓。
- 全站排查：跨视口的遮罩/渐变只有这一条；`TabRail` 的胶囊两端渐隐局限在轨道内，`Card` 的两处渐变是装饰且不跨视口。
- 守门：`tests/test_motion_coverage.py` 增 `test_bottom_veil_stays_under_the_two_side_columns`（钉住包裹 `z-30`、渐隐类名、两栏的 `z-40`）。

```
uv run --with pytest python -m pytest tests -q        → 95 passed
cd web; node scripts/check-ui.mjs                     → OK：没有违规
cd web; npm run build                                 → index-yzM_yVwJ.js 469.17 kB / gzip 153.00 kB
```

