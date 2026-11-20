# 按交互/性能评审修的一轮（2026-11-20）

对象：docs/interaction-perf-review-2026-11-20.md 的 C-01…C-08、I-01…I-09 与 P-01…P-10。
口径沿用评审：P1 = 高频操作卡顿或反馈缺失，P2 = 打磨项，不设 P0。

## 一、代码层（C / I）

| 编号 | 问题 | 改法 | 落点 |
| --- | --- | --- | --- |
| C-01 / I-02 | 卡片菜单键盘打不开 | 首次 focus 挪进依赖 `pos` 的 effect；再加卸载时把焦点还给「⋯」 | web/src/components/CardMenu.tsx |
| C-02 | 确认框不压热键栈 | 挂载时 `pushScope("dialog")`，卸载 `popScope` | web/src/components/ui/Confirm.tsx |
| C-03 | 插件开关没有开关语义 | `role="switch"` + `aria-checked` + `aria-label` | web/src/pages/SettingsPage.tsx、web/src/components/AiProviders.tsx |
| C-04 | 设置页提示条压住保存条 | flash 从 `bottom-6` 提到 `bottom-24` | web/src/pages/SettingsPage.tsx |
| C-05 / I-09 | 灯箱没有模态语义 | `role="dialog"` + `aria-modal` + `aria-label`、打开时锁焦点、Tab 首尾循环、关掉同步还焦点 | web/src/pages/ItemPage.tsx |
| C-06 | `"corner"` 形态是死代码 | 两处三元表达式改 `createGhost({ agent: "pill" })` | web/src/agent/AgentProvider.tsx |
| C-07 | 两处 toast 定时器互不取消 | toast 改对象 state + 单个 timer ref，action 5200ms / 普通 2400ms，卸载清理 | web/src/App.tsx |
| C-08 | 每个流式事件整数组复制 | `scheduleFlush`：rAF 合并，一帧最多一次 `setLive` | web/src/agent/AgentProvider.tsx |
| I-01 | 星标反馈太弱 | 乐观更新 + 「已加入/已移出稍后再看」toast + 撤销；卡片只订阅自己那条 | web/src/agent/AgentProvider.tsx、web/src/agent/savedStore.ts、web/src/components/Card.tsx |
| I-04 | 三个键都开同一个输入框 | 删掉 `mod+shift+k`；`mod+k` 与 `/` 保留 | web/src/App.tsx |
| I-05 | 收藏框还焦点要 414ms | 用 rAF 等一帧改成同步还焦点（后台页 rAF 会被节流到 1s） | web/src/pages/ItemPage.tsx |
| I-06 | 列表 j/k 是瞬移 | `scrollIntoView({ behavior: "smooth" })` | web/src/pages/FeedPage.tsx |
| I-07 | 数字输入清空变 0 | 本地 `NumberField`：草稿字符串 + 失焦 clamp、清空还原旧值 | web/src/pages/SettingsPage.tsx |
| I-08 | 收藏夹与稍后再看视觉分不清 | 收藏夹每行加实心心形 | web/src/components/FavoritesList.tsx |

## 二、性能（P）

### P-01 左栏收放

归因链（全部是实测，探针见 probes/ops_diag_left*.py、probes/ops_trace_expand.py）：

1. 关闭宽度过渡后长任务仍在 → 不是 framer-motion 的 layout 动画（`reduced_motion=reduce` 反而更差）。
2. 卡片 `display:none` 后 collapse 51ms；把卡片字号钉死 50ms 且无长任务 → **字号跨档导致 18–30 张卡全部重排**是主因。
3. 断点布局：3 列 371 → 收栏后 4 列 317 → 展开 427，正好扫过容器查询的 371–427 区间，于是每次收放都跨档。
4. CDP trace：RunTask 1465ms、Layout 178ms×7、Paint 49ms → 是重排，不是绘制。

改法：

- 卡片字号从连续 `cqw` 改成两档 `@container`（250px / 600px），断点刻意避开 360–440 这段扫过区间（守门测试钉住）。
- 列宽不做过渡（`.shell-col { transition: none }`），换宽一步到位；中间列用 200ms 位移 + 淡入（`.content-settle-expand/-collapse`）接住这次跳变。

结果（1440×900，961 条真实数据，连做 3 轮）：

| 操作 | 修前 | 修后首次 | 修后稳态 |
| --- | --- | --- | --- |
| 收起左栏 | max 160ms / 长任务 295ms | 173ms / 157ms | 40–53ms / 0 |
| 展开左栏 | 长任务 293ms | 213ms / 207ms | 27–53ms / 0 |

首次仍然是 150–210ms：这是布局缓存冷启动（第一次按 4 列宽度排版全部卡片），之后同一会话里不再复现。要彻底消掉得让收放不改变列数，那是版式取舍，不在这一轮。

> 2026-11-20 晚补：用户要求左右栏统一成「滑入滑出」，左栏改回 framer-motion 宽度补间（`Shell.tsx` 的 `motion.div`），`content-settle-*` 已删。实测稳态 13–40ms/帧、展开无长任务、收起首次 127ms 冷启动后归零 —— 与右栏关闭（p95 39ms / 长任务 50ms）同量级。详见 `docs/left-rail-tween-2026-11-20.md`。

### P-03 触底加载

每页 30 → 18 条（web/src/api.ts）。修前 feed.scroll-end max 226ms / 长任务 191ms，修后 max 66.6ms / 长任务 52ms。

### P-04 / P-05 排序与筛选

- 换条件时先关掉布局动画（`layoutSettled` 420ms 后才开），避免 FLIP 拖着一次大重排。
- 删掉 section 上的 `key={queryKey}`：换条件不再整批重挂卡片。
- 卡片包装层统一成 `motion.div`，跨 48 张阈值不再整批换元素类型。

结果：sort.hot 213ms / 长任务 202ms → 106ms / 117ms（首次），稳态 27–40ms / 0。

### P-08 预取放大

- 悬停预取只拉 `/api/item`（详情留给真点下去），去抖 260ms → 600ms。
- `openItem` 里再补 `prefetchDetail(id)`：转场 420ms 正好盖住这次请求。

### P-10 Agent 中段静默

`AgentConsole` 记录「上一次事件到现在」的秒数，静默 ≥6 秒时把「下一步…」换成「还在翻，已 Ns」，带 `aria-live="polite"`。实测：一轮 11 秒无事件的运行，第 7 秒出现该文案。

## 三、验收

- 探针：`probes/ops_frames.py` 43 个操作；单点复测 `probes/probe_star.py`、`probes/probe_left_sort.py`。
- **口径说明**：43 个操作在同一个页面里连跑，前一个操作的过渡/布局动画会算到下一个头上。为此给每次测量加了「等上一轮动画跑完再开测」（`SETTLE`：`document.getAnimations()` 里非无限动画全部 finished）。即便如此，跨轮抖动仍很大（同一构建连跑两轮，`chip.single` 一次 40ms、一次 667ms，后者无长任务、是环境抖动），所以**单点结论以连测 5 次为准**。

| 操作 | 修前 max / 长任务 | 修后 max / 长任务 | 稳定值（连测） |
| --- | --- | --- | --- |
| nav.to-item | 120ms / 61ms | 53–67ms / 0 | — |
| nav.back | 133ms / 151ms | 53–67ms / 0 | — |
| feed.scroll-end | 213ms / 170ms | 66.6ms / 52ms | — |
| sort.hot | 213ms / 202ms | 94–146ms / 87–134ms | 首次 106/117，之后 27–40ms / 0 |
| left.collapse | 160ms / 295ms | 93–160ms / 100–148ms | 首次 173/157，之后 40–53ms / 0 |
| left.expand | 长任务 293ms | 187–240ms / 168–231ms | 首次 213/207，之后 27–53ms / 0 |
| card.star | 240ms / 130ms | 160ms / 0 | 13–27ms / 0（5 次） |
| chip.esc-reset | 80–160ms | 66–133ms / 0–51ms | 40–66ms / 0（5 次） |
| drawer.key-open | 186ms | 13.5ms / 0 | — |
| menu.open | —— | 213ms / 81ms | 首次（portal 首挂 + 首项 focus） |

- 行为断言：`probes/probe_keyboard_menu.py`（菜单键盘焦点、Esc 归位、星标 toast + 撤销全过）、`probes/probe_confirm_scope.py`（确认框开着时 `?` 不叠帮助、`[` 不收左栏）。
- 门禁：`pytest` 110 passed；`node scripts/check-ui.mjs` 无违规；`npm run build` 通过（dist/assets/index-B7xLLd3F.js 491.16 kB / gzip 158.56 kB）。
- 新增守门：`test_grid_cols.py` 的断点区间断言、`test_motion_coverage.py` 的列宽无过渡、`test_perf.py` 的每页 18 条 / 悬停只取 item / 单卡订阅 / Agent 静默计数、`test_interaction.py` 的菜单还焦点与确认框压栈。

## 四、未做

- 左栏收放的首次 150–210ms：需要版式层面不让收放改变列数。
- Agent 的 plan 步骤实时打点（后端只发一次 plan）；这一轮只补了静默秒数。
- 窄屏（<1200）与 Safari / Firefox 的真机复测。
