# onefeed 交互与性能评审

日期：2026-11-20 · 评审对象：HEAD `ae4c5f1`（收藏夹与稍后再看分开）· 服务：`--demo` 库 961 条 / 7 平台
评审视角：软件测试工程师 + 前端交互设计师。只看两件事：**每次用户操作卡不卡**、**动效与反馈顺不顺**。

---

## 0 结论速览

- 全站 43 个可复现操作做了逐帧采样（rAF + longtask + 首动时刻），**15 个操作出现 ≥1 帧 >60ms 或 ≥3 个 jank 帧**，但没有一个操作「卡到不能用」——最低帧率 26.8fps 出现在左栏收放。
- 手感最好的部分：悬停/按压反馈（14.4ms / 13.6ms 内出帧）、右抽屉 240ms 全程满帧（max 14ms）、卡片菜单/列数弹层进场（19–26ms）、V T 转场（172ms 单帧，可接受）。
- 最该修的三件事：
  1. **左栏收放 295ms 长任务**（fps 26.8，最强的一次卡顿）；
  2. **星标收藏单次点击 240ms 帧 + 155ms 长任务**（高频操作，代价与「点一下」不匹配）；
  3. **确认框不隔离热键**：卸载确认框开着时按 `?` 会再叠一层帮助、按 `[` 直接把左栏收成 64px。
- 交互层最扎眼的是**反馈缺失**：卡片星标收藏后只有 16px 图标变色，没有 toast、没有撤销入口；卡片菜单打开后键盘完全失效（ArrowDown 不动）；Agent 一次问答里会出现 13 秒「界面零变化」的中段静默。

---

## 1 评审口径

| 项 | 取值 |
| --- | --- |
| 浏览器 | Chrome（headless，channel=chrome） |
| 视口 | 1440×900（主）/ 1280×860（抽屉）/ 390×844（移动端） |
| 采样 | rAF 逐帧间隔 + `PerformanceObserver('longtask')` + MutationObserver 首动时刻，窗口 700–2600ms |
| 触发方式 | 鼠标事件走 CDP `Input.dispatchMouseEvent` 直发（避免 Playwright 自动滚动/等待污染时延）；键盘走 `keyboard.press` |
| 帧定义 | jank = 帧间隔 >33ms（约 30fps）；长任务 = >50ms 的主线程任务 |
| 数据 | `.onefeed/ops-frames.json`、`.onefeed/ops-behavior*.json`，探针在 `probes/ops_*.py` |
| 库 | `python -m onefeed --demo --no-browser --port 8799`（961 条，7 平台） |

两个口径坑，先说明免得误读：
1. **合成点击 vs 真鼠标**：`element.click()` 测星标是 max 67ms，CDP 真鼠标是 max 240ms。差在指针事件 + 悬停预取被真实触发，报告以真鼠标为准。
2. 早期用 Playwright 的 `scroll_into_view_if_needed` 出现过「首动 3.5s」的假数据（它自带 4s 超时），已全部改为坐标直发。

---

## 2 覆盖矩阵：每个用户操作

### 2.1 外壳与全局

| 操作 | 实测 | 判定 |
| --- | --- | --- |
| 收起左栏（240→64） | fps 26.8，max 160ms，jank 4，**长任务 295ms/103ms**，首动 23.5ms | ❌ 全站最卡 |
| 展开左栏 | fps 53，max 93.3ms，长任务 59ms | ⚠️ 偏卡 |
| 切主题（亮/暗） | fps 68.5，max 66.6ms；切回 max 53.3ms | ✅ 可接受（0.7s clip-path 扫过） |
| 顶栏刷新 | 首动 34.3ms，max 26.8ms | ✅ |
| 帮助面板 `?` | 首动 29.7ms，Esc 11.8ms | ✅ |
| 全局 `/`、`Ctrl+K`、`Ctrl+Shift+K` | 均唤起 Agent 输入框，焦点自动落位（150ms 内） | ⚠️ 三个键做同一件事，见 I-04 |
| 回到顶部 | 首动 25.9ms，平滑滚动 | ✅ |

### 2.2 信息流

| 操作 | 实测 | 判定 |
| --- | --- | --- |
| 点平台胶囊（单选） | fps 70.2，max 40.1ms，首动 67.5ms | ✅ |
| Ctrl 多选胶囊 | max 53.2ms，jank 3 | ⚠️ |
| Esc 回「全部」 | fps 63.5，**max 160.1ms，长任务 103ms** | ❌ |
| 方向键在胶囊间移动 | 无 DOM 变化（只挪焦点，符合设计） | ✅ |
| Enter 选中 | 首动 23.4ms | ✅ |
| 排序切「按热度」 | fps 57.2，**max 186.8ms，长任务 160ms** | ❌ |
| 时间范围「今天/全部」 | max 26.7 / 80ms（66ms 长任务） | ⚠️ |
| 列数弹层打开 | fps 73.4，max 26.2ms，首动 19.2ms | ✅ |
| 选 4 列 | fps 59.4，max 80.1ms，jank 3，长任务 63ms | ⚠️ |
| 筛选框回车提交 | 首动 **1027ms**（含网络），页面自身 fps 75、不掉帧 | ⚠️ 感知慢 |
| 触底加载下一页 | fps 66.2，**max 226.8ms，长任务 191ms** | ❌ |
| 列表键盘 j / k / l / h | 焦点正确移动 + `scrollIntoView(nearest)` 保可见 | ✅（跳转是瞬移，见 I-06） |
| 卡片悬停 | max 14.4ms | ✅ |
| 卡片按下 | max 13.6ms | ✅ |
| 卡片星标收藏 | fps 43.9，**max 240.1ms，jank 5，长任务 155ms** | ❌ |
| 卡片菜单打开 | 首动 ~20ms；**键盘焦点没进菜单** | ⚠️ 见 C-01 |
| 菜单三项 | 稍后再看 / 复制原平台链接 / 查看 AI 总结，均可用 | ✅ |
| 复制链接 | 剪贴板拿到正确原帖 URL | ✅ |
| Ctrl+K 想「搜内容」 | 实际打开的是 Agent 输入框 | ⚠️ 见 I-04 |

### 2.3 打开详情（VT）

| 操作 | 实测 | 判定 |
| --- | --- | --- |
| 卡片 → 详情（共享元素转场） | fps 66.3，max 172.9ms，长任务 76ms | ⚠️ 可接受 |
| 从信息流点击进详情 | fps 63.4，max 120.1ms，jank 3 | ⚠️ |
| 返回信息流 | fps 67.6，max 93.5ms，长任务 58ms | ⚠️ |
| 详情页 tab 切换（原文/总结） | max 26.4 / 13.7ms | ✅ 很轻 |
| 收藏对话框打开 | fps 71.5，max 40ms，首动 39.9ms | ✅ |
| 收藏 Esc 关闭 | 首动 414ms、无掉帧（含焦点归还） | ⚠️ 见 I-05 |
| 写备注 → Ctrl+Enter 保存 | 保存禁用态（空备注）→ 可用 → 关闭 → 按钮变「已收藏」aria-pressed=true | ✅ |
| 复制链接按钮 | 首动 36.5ms，图标 2s 后复原 | ✅ |
| 灯箱（多图） | 打开锁滚动、序号 2/3 → → 键 3/3 → Esc 解锁、焦点回缩略图、点空白可关 | ✅（但无 dialog 语义，见 C-05） |
| 右栏 AI（详情页 rail/抽屉） | fps 73.9，max 26.8ms，首动 32.2ms | ✅ |

### 2.4 右栏 / Agent

| 操作 | 实测 | 判定 |
| --- | --- | --- |
| 抽屉打开（1280） | 首动 35.6ms，max **14ms**，240ms 过渡全程满帧 | ✅ 标杆 |
| 抽屉 Esc / `]` 关 | 6.2ms | ✅ |
| `]` 键打开抽屉 | **max 186.7ms**（同样动作鼠标路径只有 14ms） | ⚠️ 两条路径不一致 |
| Agent `/` 唤出 | 150ms 内 surface=sheet、焦点已进输入框 | ✅ |
| 发送 → 停止键出现 | **36ms** | ✅ |
| 首屏可见进展 | 36ms（先是「听着」，3.5s 出计划） | ✅ |
| 流式期间帧 | 长任务 0，无掉帧 | ✅ |
| **中段静默** | 8.4s 之后到 21.4s 之间界面文字零变化（13s） | ❌ 感知卡死 |
| 整轮耗时 | 20–37s（Agent 自报 7.2s 执行） | ⚠️ |
| 停止 | 点「停止这一轮」→ 2.5s 内出现「已按你的要求停下」+ 已得结果 + 后续动作 | ✅ |
| 历史面板/会话列表 | 可开关、按今天/昨天/更早分组 | ✅ |

### 2.5 设置页

| 操作 | 实测 | 判定 |
| --- | --- | --- |
| 左侧导航跳转 | 滚到「已装插件」后 scrollY=1559 | ✅ |
| 折叠区展开 | 有动画、无掉帧 | ✅ |
| 数字输入清空 | 显示 0（不出现 NaN/空） | ⚠️ 静默改成 0，见 I-07 |
| 保存（改每轮条数） | flash「已保存：每轮条数 → 13」、保存条消失、`/api/settings` 读到 13 | ✅ |
| 保存时 flash 与保存条 | 同一 y（817–830）、z 50 vs z 40 | ⚠️ 同槽重叠，见 C-04 |
| 放弃改动 | 保存条消失 | ✅ |
| 插件开关点击 | 状态切换成功（按钮 title 变「点击停用（不上场）」） | ✅ |
| 插件开关语义 | `role=null`、`aria-checked=null`、`aria-pressed=null` | ❌ 见 C-03 |
| 清空 key（requireTyping） | 未输入 CLEAR 时「清除」disabled | ✅ |
| 卸载插件 | 确认框（含后果说明）→ 已装 7→6 → 撤销条「已卸载：bilibili 撤销」→ 撤销后恢复 7 | ✅ |
| 移动端 390×844 | 无横向溢出、一列 30 卡；小目标：刷新/主题/市场/设置 36×36，分段控件 44×26 | ⚠️ 尺寸偏小但可用 |

---

## 3 代码问题

### C-01 卡片菜单：打开后键盘焦点没进菜单，ArrowDown 全失效（P1）
`web/src/components/CardMenu.tsx:35-45,73`：`useLayoutEffect` 里先 `setPos(...)`，紧接着 `ref.current?.querySelector('[role="menuitem"]')?.focus()`；但同组件 `if (!pos) return null`，**首次渲染 ref 为 null，focus 这句永远拿不到节点**，而 `pos` 更新后 effect 不会重跑。
实测：打开菜单后 `document.activeElement` 仍是「更多操作」按钮（aria-expanded=true），按 ArrowDown 前后 activeElement 相同；Esc 能关是因为 document 级捕获监听，与菜单自身键盘模型无关。
影响：菜单「看起来可键盘操作」实际只能用鼠标，读屏/键盘用户无法进入。
修：把 focus 挪到 `pos` 生效后的 `useEffect`（依赖 `pos`），或先渲染容器再定位。

### C-02 确认框不压入热键栈，全局热键穿透（P1）
`web/src/components/ui/Confirm.tsx`（全文无 `pushScope`）只在弹窗 `motion.div` 上挂 `onKeyDown={trap}`；热键栈顶仍是 `global`。
实测（卸载 bilibili 确认框打开时）：
- 按 `?`：帮助面板同时打开（`[role=dialog]` 从 1 变 2）；
- 按 `[`：左栏宽度 240px → 64px（弹窗后面整块布局在动）。
带输入框的确认框（清 key 需键入 CLEAR）因为 `isTyping` 挡住了单键热键，所以看着没事——**问题只出现在无输入确认框**：卸载插件、移出收藏夹、退出登录、恢复默认都是这一类。
修：ConfirmHost 挂载时 `pushScope("dialog")`、卸载时 `popScope()`，与 Shell/App 的 drawer、help 保持一致。

### C-03 插件开关没有开关语义（P1，a11y）
`web/src/pages/SettingsPage.tsx` 的开关是 `button` + `h-6 w-11` 轨道，实测 `role=null / aria-checked=null / aria-pressed=null`。
修：补 `role="switch"` + `aria-checked={enabled}` + `aria-label`，或干脆用原生 checkbox 视觉隐藏。

### C-04 设置页 flash 与保存条同一槽位（P2）
- 保存条：`fixed bottom-6 left-1/2 z-40`（`SettingsPage.tsx:386`）
- flash：`fixed bottom-6 left-1/2 z-50`（同文件 836-843）
实测两者 y 都在 817–830。保存成功的瞬间 flash 会盖住保存条 3.2s（此时保存条本就该消失，冲突窗口小）；但任何「保存失败」也会把「放弃」按钮压住——建议 flash 上移到保存条上方（bottom-24）或让两条共用同一容器排队。

### C-05 灯箱没有 dialog 语义、没有焦点陷阱（P2，a11y）
实测灯箱打开时 `[role=dialog]` 数量为 0（`document.querySelectorAll('[role=dialog]').length === 0`），面板是 `fixed z-[60] bg-black/90` 的普通 div；Esc / ←→ / 点空白 / 点图切 zoom 都正常，body 滚动也确实锁了，但 Tab 会跑到背后的页面元素里，读屏也不会把它当模态。
修：`role="dialog" aria-modal="true" aria-label="图片查看器"` + 打开时 `pushScope("dialog")` + Tab 循环。

### C-06 Agent 关闭时「corner」分支是死代码（P2）
`web/src/agent/AgentProvider.tsx:699`：`createGhost({ agent: onItemPage && wide ? "corner" : "pill" })` 位于 `onItemPage && wide` 已被上面 `return` 掉的分支里，条件恒为 false → 永远走 `"pill"`。要么删掉三分支，要么把上面的 early return 改成设置标志位，否则「详情页宽屏收起时缩到右下角」这个设计意图从未生效。

### C-07 两处 toast 语义重复、定时器互相打断（P2）
`web/src/App.tsx:66-75`：`onefeed:toast` 监听里 `setToast(text)` + `setTimeout(() => setToast(""), 2400)`，**旧 timer 不取消**；`refresh()` 里另外挂了 `setTimeout(..., 3200)`（`:158`）。连续两条 toast 时，第一条的 2.4s timer 会提前把第二条清掉；`refresh` 的 3.2s 也会和 2.4s 打架。
修：用 `useRef` 存 timer，进入时先 `clearTimeout`。

### C-08 流式事件整数组复制（P2，性能隐患）
`AgentProvider.tsx:386`：每个事件都 `setLive({ run_id, events: [...events] })`，事件数线性增长 → O(n²) 复制 + 所有订阅者重渲染。本轮实测没有长任务（事件少），但一轮 200+ 事件、或多轮 resume 后会显现代价。
修：`useSyncExternalStore` 或把 live 事件放 ref、只对`events.length` 节流渲染（`requestAnimationFrame` 合帧）。

---

## 4 交互问题

### I-01 星标收藏后反馈太弱（P1）
实测点星标：只有 16px 图标由描边变实心、`aria-label` 改成「移出稍后再看」，**没有 toast，也没有撤销入口**（`toast: None`；页面里找不到「撤销」按钮）。同页的「卸载插件」却有完整撤销条——同一个产品两套反馈标准。
点错一下只能再点一次去撤销，而卡片右下角的星标在悬停前不可见。
建议：收藏成功给 2.4s 轻提示 + 「撤销」；或复用保存条那套底部胶囊。

### I-02 卡片菜单键盘不可用（P1）
见 C-01。设计上菜单支持 ↑↓ 循环 + Esc 关闭，但焦点没进去，等于键盘用户只能「打开一个什么都不响应的浮层」。

### I-03 确认框开着还能触发全局热键（P1）
见 C-02。卸载确认框背后左栏会在 260ms 内收成 64px，弹窗位置不动、背景整块位移——视觉上像「弹窗在飘」。

### I-04 Ctrl+K 打开的是 Agent，不是搜索（P2）
`web/src/App.tsx:170-176`：`/`、`mod+k`、`mod+shift+k` 三个键都 dispatch `onefeed:ask`。Ctrl+K 在几乎所有制图工具/编辑器里是「搜索」，在这里打开 Agent 输入框——如果这是有意（Agent 优先）也至少该在帮助面板里写明；`mod+shift+k` 与 `mod+k` 完全重复，属冗余绑定。

### I-05 收藏对话框 Esc 关闭要 414ms 才把焦点还给触发按钮（P2）
实测 `item.fav.esc` 首动 414.2ms（无掉帧）。原因是关闭后 `rAF` 才把焦点还回去，再叠加过渡。观感是「按了 Esc 之后停半拍才看到按钮亮起焦点环」。建议关闭动画与还焦点并行，或直接把还焦点放进 `close()` 同步执行。

### I-06 列表 j/k 跳转是瞬移（P2）
`scrollIntoView({ block: "nearest" })` 是瞬时滚动，连按 j 时视觉上是一格一格「啪」地跳，没有平滑跟随。若要「丝滑」，改成 `scrollIntoView({ block: "nearest", behavior: "smooth" })` 并加 120ms 冷却，避免连续按键时滚动被不断打断。

### I-07 数字输入清空后静默变 0（P2）
`SettingsPage` 的 `per_plugin_limit / comments_limit / prune_days`：`onChange` 直接 `Number(value)`，空串 → 0；实测清空后输入框显示 `0`。用户以为「清空了没改」，其实已经改成 0（保存后可能意味着「不采集」）。建议保留空态、失焦时回填原值或给行内校验。

### I-08 已收藏状态与「收藏夹/稍后再看」两套数据看起来一样（P2）
详情页「收藏」按钮与卡片星标（稍后再看）在视觉上都是「星/心 + 已选」，但一个进收藏夹（要写备注）、一个进稍后再看。新用户会把两者混为一谈；建议星标 hover 时带 title「稍后再看（不写备注）」、收藏夹按钮文案明确「收藏并记一句」。

### I-09 灯箱缺模态语义（P2）
见 C-05。Tab 会离开灯箱、读屏不知道有模态层。

---

## 5 性能问题

按代价排序（实测，1440×900）：

### P-01 左栏收放：295ms 长任务 + 4 个 jank 帧（P1）
`left.collapse` fps 26.8、max 160ms、长任务 295ms/103ms；展开也有 59ms 长任务。
怀疑点（未做 profile 归因）：`.shell-col` 的 `transition: width 260ms cubic-bezier(0.22,1.24,0.36,1)` 会让内部 **30 张卡片每帧重新布局**（卡片是 `container-type: inline-size`，宽度变化 → `cqw` 变化 → 字号/高度全变）；同时 AgentSidebar 的 240/64 双层 `.side-layer` 交叉淡入。
验证方法：Profile 里看 Layout 占比；若确认为容器查询重排，把收放改为 `transform: translateX` + 内容不做容器查询，或收放期间给 feed 加 `contain: layout`。

### P-02 星标收藏：240ms 帧 + 155ms 长任务（P1）
单点操作 240ms 是明显的「顿一下」。可能由三件事叠加：
- 悬停进入卡片时 260ms 后触发 `prefetchItem`（`Card.tsx:291`）——实测慢划过 6 张卡发 12 个请求（item + detail 各一），同时正在解析详情 JSON；
- `toggleSave` 依赖 `[saved]`（`AgentProvider.tsx`），每次点星标都重建 actions context → 依赖它的组件全量重渲染；
- 收藏后 dispatch `onefeed:saved`，右栏 SavedList 与侧栏计数同时刷新。
建议：`prefetchItem` 改成 `requestIdleCallback`；`toggleSave` 用 `useCallback` 配合 ref 读 saved，断掉对 `saved` 的依赖；`onefeed:saved` 的监听方加节流。

### P-03 触底加载下一页：226ms 帧 + 191ms 长任务（P1）
一次追加 30 张卡（每张带封面、头像、platform tint、motion `layout="position"`）。建议：追加批次降到 12–15 张、或对新批次关闭 layout 动画（只保留 `.rise` 的 CSS keyframes），并用 `content-visibility: auto` 处理离屏卡片。

### P-04 排序切换：186ms 帧 + 160ms 长任务（P1）
「按热度」会整列表重排；`motion.div layout="position" layoutDependency={grid.cols}` 在 items 变化时仍做位置测量。建议：排序变化时把 `layout` 动画关掉（相当于一次整页换内容），只保留进场 `rise`。

### P-05 Esc 回「全部」：160ms 帧 + 103ms 长任务（P1）
与 P-04 同源（胶囊高亮反色扫过 + 列表整批替换）。修一个另一个也会轻。

### P-06 键盘 `]` 打开抽屉 186ms，鼠标只有 14ms（P1，不一致）
同一个可视结果两条路径代价差 13 倍。鼠标路径走 `openRight(true)` + CSS 过渡；键盘路径走 `onefeed:rail` 事件（`Shell.tsx`）→ `setRailTab` + 可能先 `close()` 再 `openRight(true)`，中间多一轮渲染 + 页签内容挂载。建议统一走同一个状态更新函数，并让首次挂载的内容用骨架占位。

### P-07 筛选提交首动 1027ms（P1，感知）
页面自身不掉帧，慢在网络 + 首屏 30 卡挂载。建议：提交后立刻渲染骨架（当前只在无 seed 时 loading），并把筛选结果的第一页请求与详情预取并行。

### P-08 悬停预取的网络放大（P2）
实测：慢划过 6 张卡 = 12 个请求（`/api/item/:id` + `/detail`），快速划过 = 0（说明 260ms 去抖有效）。建议：只为「停留 >600ms」或「即将进入视口中心」的卡片预取；详情请求在 hover 时只预取 `item`（列表已有），详情等点击时再拉。

### P-09 头像 16×16 拉原图、封面无缩略图（P2，存量问题）
`Card.tsx:356` 头像 `h-4 w-4` 直接用 `author_avatar` 原图；封面无 `decoding="async"`/`fetchpriority`，也没有缩略图尺寸参数。切换筛选时是图片洪峰（perf-audit 的 PF-7/PF-12 仍未修）。建议在 API 侧加 `?w=96` 或前端用 `<img sizes>` + CDN 参数。

### P-10 Agent 中段 13 秒无可见变化（P1，感知性能）
时间线（可见文本长度）：33ms 出现停止键 → 408ms 有「听着」→ 3.5s 出计划 → 5.8s / 8.4s 各推进一次 → **8.4s–21.4s 无任何变化** → 结果。
建议：把「正在检索/正在读第 N 条」的进度事件做成顶部细进度条或逐条打点（已有 `AgentConsole` 的 plan 步骤，可让步骤状态实时更新并在长时间无事件时给「还在翻，已 12s」的提示）。

---

## 6 改进建议（按优先级）

**P1（本轮建议修）**
1. `ConfirmHost` 接入 `pushScope("dialog")`（C-02/I-03）——改动 5 行，消除热键穿透。
2. 修 `CardMenu` focus（C-01/I-02）——把 focus 放进依赖 `pos` 的 effect。
3. 星标收藏补反馈：轻提示 + 撤销（I-01）；同时按 P-02 断掉 `toggleSave` 的 `[saved]` 依赖。
4. 左栏收放按 P-01 做归因 profile，先尝试「收放期间 `contain: layout` + 停掉卡片容器查询重算」。
5. 排序/筛选切换时关闭 layout 动画（P-04/P-05）。
6. Agent 流式补中段进度（P-10）。

**P2（打磨）**
7. 插件开关补 `role="switch"` + `aria-checked`（C-03）。
8. 灯箱补 `role="dialog"` + 焦点陷阱（C-05/I-09）。
9. toast 定时器清理 + 设置页 flash 槽位上移（C-04/C-07）。
10. 删掉 `mod+shift+k` 冗余绑定，帮助面板标注 Ctrl+K 是 Agent（I-04）。
11. 数字输入空值不静默变 0（I-07）。
12. 列表 j/k 平滑滚动 + 冷却（I-06）。
13. 触底追加批次减小 + 离屏 `content-visibility`（P-03）。
14. 悬停预取只取 item、延后 detail（P-08）。

**验收口径（复用本轮探针）**
- `probes/ops_frames.py`：每个操作 max 帧 <60ms、无 >150ms 长任务；
- `probes/ops_behavior*.py`：C-01/C-02/C-03 三条改为断言（菜单 activeElement 在 `[role=menuitem]` 内；确认框开着时 `[role=dialog]` 数量恒为 1 且左栏宽度不变；开关 `aria-checked` 非 null）。

---

## 7 未覆盖 / 未能复现

| 项 | 原因 |
| --- | --- |
| 设置页保存「registry」字段被一起写 | 保存时 flash 显示「已保存：每轮条数 → 13；registry → …」，说明提交体里 registry 与当前值不同。数据影响不明，**待确认是否为表单默认值与后端默认值不一致**，未在报告中定性。 |
| 插件「安装/更新」（非卸载） | 需要真实市场下载，demo 环境不联网拉包。 |
| 登录态（小红书/抖音/B 站扫码） | 需要账号扫码，未操作。 |
| 详情页 AI 总结整段流式（打字机 60 字/秒） | 依赖 LLM 服务，本轮只抓到「Agent 正在看这条内容… 3s」的等待态（正常）。 |
| 灯箱多图真实数据 | demo 库每条笔记 `images ≤ 1`，多图路径用路由注入三图验证（已通过），非真实条目。 |
| 移动端手势（下拉、横滑） | 仅验证了 390×844 布局与目标尺寸，未做触摸滑动帧率。 |

---

*方法与数据可复现：`probes/ops_frames.py`、`probes/ops_behavior.py`、`ops_behavior2/3/4/5/6.py`、`probes/diag_*.py`；原始 JSON 在 `.onefeed/`。*
