# OneFeed Agent 交互重设计（2026-11-19）

> 触发：实测问「今天 B 站有什么值得看的 AI 相关内容吗」，Agent 执行了命令、流式输出了过程，然后直接打开一个视频——详情页里没有 Agent，刚才那段对话和轨迹一起消失了。
>
> 本文只给方案，不改代码。文末给出 P0/P1/P2 分期与可执行验收。

## 0. 一句话结论

割裂不是「详情页少一个按钮」，而是**会话状态被放在了页面组件里**：`web/src/components/AiDock.tsx` 只在 `web/src/pages/FeedPage.tsx:376` 挂载，Agent 一旦导航到 `/item/:id`，AiDock 随 FeedPage 卸载，`turns`/`live` 全部丢失，只剩 localStorage 里的 `threadId`。
所以正确解法是三步：**会话状态上提到 shell 级单例（AgentProvider）→ 入口按页面就地提供（详情页右栏/抽屉）→ 线程与事件走后端续传（已有 `events?after`）**。

---

## 1. 现状与根因

### 1.1 三个现场

| 现场 | 代码事实 | 用户看到 |
| --- | --- | --- |
| Agent 打开条目就「失忆」 | AiDock 挂在 FeedPage（`FeedPage.tsx:376`），路由切到 `/item/:id` 后组件卸载；`turns`、`live`、`busy` 都是组件内 `useState`（`AiDock.tsx:44-80`） | 视频页干净得像没聊过，回到首页也是空的 |
| 详情页没有入口 | App 的 `<Routes>` 里没有任何 Agent 挂载点（`App.tsx:152-179`） | 想追问「这条和同题的差别」，只能先返回首页 |
| 历史只能从首页弹层进 | 面板头「最近的对话」在 AiDock 内部（`AiDock.tsx` history state） | 详情页、设置页都摸不到历史；`/agent` 这种深链不存在 |

### 1.2 但底子已经够用

- 线程是后端实体：`agent_threads` / `agent_runs`，`store.recent_threads()`（`onefeed/store.py:634`）、`store.thread_runs()`（:645）。
- 事件可按序号补发：`GET /api/agent/runs/{run_id}/events` 读 `last-event-id` 头做 `after` 续传（`onefeed/api.py:259-269`），`events_after()` 在 `onefeed/agent_runtime.py:163`。
- 已有 `GET /api/agent/threads`、`GET /api/agent/threads/{id}`（`api.py:321/328`），线程可回放。
- `AgentConsole` 已经把 plan / step / action / need_answer / confirm / error 渲染成时间线，形态切换时直接复用。

**结论：后端不用改协议，只补两处小字段；工作量 80% 在前端结构。**

---

## 2. 设计原则

1. **Agent 是壳层，不是页面组件。** 挂在 `<Routes>` 之外、Provider 之下，路由变化不卸载。任何导航（包括 Agent 自己触发的）都不中断会话。
2. **一处状态，多处呈现。** 单例 `AgentSession`（threadId / turns / live / busy / pendingAsk）是唯一数据源；底部抽屉、详情页右栏、`/agent` 页面都是它的「视图」，不是各自的副本。
3. **入口就地。** 每个页面给与自己内容相关的唤起方式：信息流问筛选、详情页问这条、设置页问配置；而不是把所有场景塞进一个全局输入框。
4. **可离开、可回来。** 关闭 = 收起，不是结束。正在跑的轮次继续跑，回来接着看；刷新也能接上。

---

## 3. 信息架构：三形态 + 两页面

### 3.1 三形态

| 形态 | 尺寸/位置 | 出现场景 | 承载 |
| --- | --- | --- | --- |
| **A 唤起器 Collapsed** | 信息流：底部胶囊输入条（现状）；详情页：右下 44px 悬浮按钮；其他页同 | 默认态 | 一句提示 + `/` 快捷键；正在跑时显示一行状态点 |
| **B 抽屉 Sheet** | 底部抽屉，宽 `max-w-760`，高 42–62vh | 点唤起器 / `/` / `⌘K`；窄屏详情页 | 一轮对话 + 轨迹 + 结果卡 |
| **C 侧栏 Rail** | 右侧 380px 常驻栏（≥1080px） | 详情页「展开」；或从抽屉「停到右边」 | 同一轮对话，纵向空间更大，不遮播放器 |

### 3.2 两页面

| 路由 | 内容 | 说明 |
| --- | --- | --- |
| `/agent` | 左列历史线程（标题/轮数/时间/状态），右列空态或最近线程 | 对话主页，可深链 |
| `/agent/:threadId` | 同上，右列加载该线程并接续 | 刷新、分享、从历史点开都落到这里 |

### 3.3 形态切换关系

```text
        ┌──────────── 收起（Esc） ────────────┐
        ↓                                      │
  [A Collapsed] ──点/「/」/⌘K──▶ [B Sheet] ──「停到右边」──▶ [C Rail]
        ↑                            │  ↑                      │
        └──────── Esc / 关闭 ─────────┘  └──── 收起为抽屉 ──────┘
                                     │
                               「全屏」/历史点开
                                     ↓
                              [D/E /agent 页]
```

切换规则（重要）：
- 形态切换**不重建 session**，只换宿主容器；正在跑的 SSE 连接保持（Provider 持有）。
- 记住上次形态：`localStorage["onefeed.agent.surface"] = "sheet" | "rail"`，详情页再次进入时按记忆恢复。
- `Esc` 在 Sheet/Rail 里一律「收起」；若正在跑，收起不取消，唤起器上显示「正在跑 · 点开看」。

---

## 4. 详情页方案（正面解决割裂感）

### 4.1 布局

```text
┌ TopBar ───────────────────────────────────────────────┐
│ hero：媒体框（共享元素 of-media） + h1（of-title）      │
├───────────────────────────────┬───────────────────────┤
│ 左列（主内容，自适应）          │ 右列 Agent Rail 380px │
│  [AI 总结] [原文]              │  ┌ 正在看：<标题> ×┐  │
│  SummaryPanel / Media          │  │ turns + 轨迹     │  │
│  同题 / 评论 / tags            │  │ [composer]       │  │
└───────────────────────────────┴───────────────────────┘
```

- `≥1080px`：右栏默认展开（可收起），用 **CSS Grid `grid-template-columns: minmax(0,1fr) 380px`**，而不是给主内容加 padding——避免「收起时内容宽度跳变」。
- `<1080px`：右栏不存在，改为底部 Sheet；hero 下方插一行「问这条」按钮，点开即带上下文。
- 右栏收起时保留 44px 竖条（一个图标 + 未读点），保证随时能拉回来。

### 4.2 上下文注入（关键）

详情页唤起时，自动把当前条目作为上下文带上：

- 前端：`AgentProvider` 暴露 `setFocus({ itemId, title, platform, kind })`；`ItemPage` 在 `item` 落地后写入，离开时清空。
- 请求：`agentStart()` 增可选 `context: { item_id, title, platform }`；后端 `POST /api/agent/runs` 读 `payload["context"]`，注入到系统提示的最后一小段（「用户此刻正在看：<标题>（<平台>）。相关提问默认指这条。」），**不改工具集**。
- UI：右栏顶部一枚可关闭的 chip「正在看：<标题>」，点 × 表示「这轮先不针对这条」。
- 价值：用户在视频页问「这条讲了啥」「和同题那条差别在哪」不用重复贴标题；这是 Copilot / Claude 类产品里「当前上下文」的标准做法。

### 4.3 三个预设动作

右栏空态给三枚 chip，点了等于发一句话（不是新入口，不增加概念）：

| chip | 实际发送 |
| --- | --- |
| 总结这条 | 总结一下我正在看的这条，三句话以内 |
| 和同题比 | 这条和「同一件事还出现在」里的其它平台版本，说法有什么不同 |
| 收藏并记一句 | 把这条收藏，并记一句为什么值得看 |

### 4.4 Agent 打开条目时会发生什么

- Agent 调 `ui_open_item` → `navigate("/item/"+id)`，Provider 不卸载，SSE 不断。
- 详情页右栏立刻显示**刚才那轮**的 turns（同一个 session），并自动滚到最新。
- 若 Agent 是「打开一条然后继续总结」，用户看到的是右栏里轨迹继续长，而不是页面跳走、对话消失。
- 返回信息流：抽屉里那轮还在（session 未清），与详情页看到的是同一份。

---

## 5. 历史对话

### 5.1 查看

- 入口三处：抽屉/侧栏头部「最近的对话」；TopBar 新增「对话」图标（aria-label，⌘⇧H）；`/agent` 直达。
- 列表项：标题（首句自动截 20 字）、`N 轮`、相对时间、状态点（进行中 / 已完成 / 已停止 / 出错）。
- `/agent` 左列支持按标题过滤（前端过滤即可，`recent_threads` 默认 20 条，够了；超过再加后端 `?q=`）。

### 5.2 继续

- 点历史项 → `/agent/:threadId`，`getThread(id)` 回放 `runs`；下一次发送带 `thread_id`，模型接着上下文。
- 若该线程最后一条 run 状态是 `running`：**重建 EventSource 并带 `after=最后已渲染 seq`**，续上未收完的事件；历史 trace 不重复渲染。
- 「开一段新的」清空 threadId，不动历史。

### 5.3 管理（P1/P2）

| 动作 | 行为 | 后端 |
| --- | --- | --- |
| 重命名 | 行内编辑 | `PATCH /api/agent/threads/{id}`（新增，改 title） |
| 删除 | `confirmDialog`（已有组件） | `DELETE /api/agent/threads/{id}`（新增，连带 runs） |
| 分叉 | 「从这轮另开一段」 | 前端新建 thread，把该轮前的 history 带上 |
| 导出 | 导出 Markdown（复用对话渲染） | 纯前端 |

---

## 6. 状态与持久化（回答待补充项）

### 6.1 结论

**需要多轮持久化，也需要跨页面保持会话状态**，理由是产品形态本身：

1. Agent 的动作天然会导航（打开条目、改筛选、去设置补 key）。若会话跟页面走，就注定「打开即消失」。
2. 线程本来就是后端实体，持久化不是新增成本，而是把已有能力接到 UI 上。
3. 用户对 Agent 的预期是「一段连续的对话」，不是「每次点开都是新话题」。

### 6.2 三层持久化

| 层 | 存什么 | 存在哪 | 生命周期 |
| --- | --- | --- | --- |
| L1 会话指针 | 当前 `threadId`、上次形态、草稿输入 | `localStorage`（`onefeed.agent.thread` / `.surface` / `.draft`） | 关浏览器还在 |
| L2 线程内容 | 线程元数据 + 每轮 input/reply/status/trace | 后端 `agent_threads` / `agent_runs` / `agent_steps`（已有） | 长期，可管理 |
| L3 运行中事件 | 未收完的 SSE 事件 | 后端按 `seq` 存档（已有），前端记最后 `seq` | 一次 run 的生命周期 |

### 6.3 明确不做

- 跨设备同步（本地单机工具，没有账号体系）。
- 长期记忆/偏好画像（超出本轮范围，放 roadmap）。
- 多标签页并发写同一线程的冲突提示（P2 可选：`storage` 事件只同步线程指针）。

---

## 7. 前端结构改造

### 7.1 组件树（before → after）

```text
before:                          after:
App                              App
├ TopBar                         ├ AgentProvider            ← 会话单例
├ Routes                         │ ├ TopBar
│ ├ FeedPage                     │ ├ Routes
│ │ └ AiDock  ← 只在这里          │ │ ├ FeedPage（删 AiDock）
│ ├ ItemPage（无 Agent）          │ │ ├ ItemPage（注入 focus + 右栏挂点）
│ ├ MarketPage                   │ │ └ ...
│ └ SettingsPage                 │ └ AgentSurface           ← 全局挂载点
└ Toast                         │   ├ AgentDock（Sheet）
                                 │   ├ AgentRail（详情页侧栏）
                                 │   └ AgentLauncher（Collapsed）
                                 └ Toast / ConfirmHost
```

### 7.2 文件清单

| 文件 | 动作 | 内容 |
| --- | --- | --- |
| `web/src/agent/AgentProvider.tsx` | 新增 | context + reducer：threadId、turns、live、busy、stopping、pendingAsk、surface、focus；方法 `ask/stop/answer/confirm/resume/newThread/setSurface/setFocus`；SSE 在这里建，`useRef` 单例防 StrictMode 双连 |
| `web/src/agent/AgentSurface.tsx` | 新增 | 根据 `surface` + 路由渲染 Dock / Rail / Launcher；全局 `onefeed:ask` 监听 |
| `web/src/components/AgentDock.tsx` | 由 `AiDock.tsx` 拆出 | 只保留「面板 + composer + 结果卡」（视觉），数据全从 context 取 |
| `web/src/components/AgentRail.tsx` | 新增 | 详情页右栏：上下文 chip + turns + 轨迹 + composer；「收起为抽屉」按钮 |
| `web/src/components/AgentLauncher.tsx` | 新增 | 底部胶囊（信息流）/ 右下圆钮（其它页）；显示运行状态点 |
| `web/src/components/AgentHistory.tsx` | 新增 | 线程列表（抽屉内紧凑版 + `/agent` 左列完整版共用） |
| `web/src/pages/AgentThreadPage.tsx` | 新增 | `/agent` 与 `/agent/:threadId` |
| `web/src/App.tsx` | 改 | Provider 包裹 + `<AgentSurface/>` + 路由两条 |
| `web/src/pages/FeedPage.tsx` | 改 | 删 `<AiDock/>`（:376）与相关 import；底部留白交给 Surface |
| `web/src/pages/ItemPage.tsx` | 改 | `useEffect` 写 focus；≥1080 渲染右栏容器（Grid）；hero 下「问这条」按钮 |
| `web/src/api.ts` | 改 | `agentStart` 增 `context`；新增 `renameThread/deleteThread` |
| `onefeed/api.py` | 改 | `/agent/runs` 读 `context` 注入提示；新增 PATCH/DELETE thread |

### 7.3 上下文拆分（避免全站重渲染）

不要把「流式 token 每 30ms 变一次」的 turns 放进和 surface 同一个 context：

- `AgentSessionContext`：threadId/turns/live/busy（高频）
- `AgentSurfaceContext`：surface/open/focus（低频）
- `AgentActionsContext`：方法（稳定引用）

消费方按需订阅；TopBar 只听 surface，避免每帧重渲染。

---

## 8. 动效与流式（保留现有能力）

- **流式不重做**：`AgentConsole` + SSE 事件原样搬到 Provider；`ItemPage` 的打字机（`shownCount` 60 字/秒下限）不动。
- **形态切换**：Sheet→Rail 用 `layoutId` 让 composer 从底部条「长」到右栏底部（0.24s，`EASE`）；Rail→Page 用 `runNav("tab")` 的 View Transition（已有封装 `web/src/motion/nav.ts`）。
- **轨迹折叠（新）**：一轮结束后轨迹收成一行「4 步 · 12.4s」可展开；正在跑时保持展开。长对话里这是降噪的关键。
- **运行指示**：Launcher 上呼吸点；文档标题前缀「● 」；详情页右栏收起时竖条上一个点。
- 不上「每个跳转都飞」——只在形态切换与 `/agent` 进出时用。

---

## 9. 键盘与可达性

| 键 | 作用 | 备注 |
| --- | --- | --- |
| `/`、`⌘/Ctrl+K` | 唤起并聚焦输入框 | 已有，`useHotkeys` 已 `preventDefault` |
| `Esc` | 收起（不取消） | 正在跑时提示「还在跑，收起不影响」 |
| `⌘/Ctrl+⇧+H` | 历史 | 新增 |
| `F6` | 主内容 ⇄ Agent 栏 | 桌面 Rail |
| `↑`（输入框空时） | 取回上一条提问 | P2 |

- Sheet/Rail：`role="dialog"` 仅 Sheet 需要；Rail 是常驻区域，用 `role="complementary"` + `aria-label="Agent"`，不抢焦点、不设焦点陷阱。
- `aria-live="polite"` 在轨迹容器（已有），错误改 `assertive`；`pendingAsk` 出现时把焦点送到选项组（现在只渲染不聚焦）。
- 详情页右栏可收起后，主内容 `tabindex` 顺序不变。

---

## 10. 移动端（<768）

- Launcher：底部胶囊固定 `pb-[env(safe-area-inset-bottom)]`。
- 展开：全高 Sheet（85vh），`visualViewport` 监听键盘高度，composer 始终可见。
- 详情页：「问这条」按钮在 hero 下方，点开即带 focus；不做右栏。
- 历史：`/agent` 单列，线程列表 → 线程详情二级页。
- 不做：分屏、拖拽调整高度（P2）。

---

## 11. 分期与验收

### P0（半天，先解决割裂）

1. `AgentProvider` + `AgentSurface`，App 挂载；FeedPage 删 AiDock。
2. 详情页 `setFocus` + 「问这条」按钮 + 底部 Sheet 复用。
3. `/agent`、`/agent/:threadId` 最小版（列表 + 回放 + 继续）。
4. `agentStart` 带 `context`，后端注入当前条目。

**验收**
- 首页问「今天 B 站有什么 AI 内容」→ Agent 打开视频 → 详情页能看到刚才的轮次与轨迹，能直接追问「这条讲了啥」，回答里出现该条标题。
- 在详情页刷新 → `threadId` 恢复，`getThread` 回放出来。
- 从详情页返回首页 → 抽屉里仍是同一轮，不重复发问。

### P1（1 天）

1. 桌面 Rail + 形态记忆 + 收起竖条。
2. 历史管理：重命名、删除（`confirmDialog`）、运行中线程续传（`after=seq`）。
3. `⌘⇧H`、F6、pendingAsk 自动聚焦。
4. 轨迹完成后折叠。

**验收**
- 1280 宽详情页右栏常驻，播放器不被遮挡；收起后主内容宽度不跳。
- 杀掉后端再重启（模拟断流）→ 重新打开线程，事件从 `after` 续上，不重复。
- 删除线程需二次确认，删完列表即时消失。

### P2（0.5–1 天）

分叉、导出 Markdown、多标签指针同步、上一条提问、Launcher 状态点、`/agent` 搜索。

---

## 12. 风险与取舍

| 风险 | 应对 |
| --- | --- |
| StrictMode/HMR 下 SSE 双连接 | Provider 里用 `useRef` + 模块级 `Map<runId, EventSource>` 做单例；卸载只在真正 unmount 时关 |
| 高频 turns 导致全站重渲染 | 三个 context 拆分（见 7.3），TopBar 不订阅 turns |
| 右栏挤压导致布局抖动 | Grid 固定列宽 + 主内容 `minmax(0,1fr)` + 卡片网格在 `xl` 以下降列；过渡只动 `grid-template-columns` |
| Sheet 遮住播放器 | 详情页窄屏 Sheet 默认 62vh 且不自动展开；「问这条」才开 |
| 历史无限增长 | 列表分页 20 条；P2 加 90 天清理或导出后删 |
| Agent 筛条件与用户手动筛选打架 | 保留现状：Agent 下发 `ui_filter` 后 toast「按 Agent 的条件筛的」+ 一键「撤销筛选」 |
| 收起后不知道还在跑 | Launcher 呼吸点 + 标题前缀 + 重开时滚到 live |

---

## 13. 与现状的差异清单（逐文件）

| 文件:行 | 现在 | 改成 |
| --- | --- | --- |
| `web/src/pages/FeedPage.tsx:376` | `<AiDock onOpenItem={openItem} />` | 删除；入口由 `<AgentSurface/>` 全局提供，通过 context 调 `openItem` |
| `web/src/components/AiDock.tsx:44-80` | 会话状态在组件内 | 迁到 `AgentProvider`；组件只做视图 |
| `web/src/components/AiDock.tsx:57-75` | threadId 读写 localStorage | 逻辑保留，搬到 Provider（同一个 key，平滑迁移） |
| `web/src/App.tsx:152-179` | Routes 外包一层 `motion.div` | 再包 `<AgentProvider>`，Routes 后挂 `<AgentSurface/>`（在 `main` 内、Routes 外） |
| `web/src/pages/ItemPage.tsx:519-522` | `Shell` 单列 | `≥1080` 改成两列 Grid，右列 `<AgentRail/>` |
| `onefeed/api.py:227-256` | 不认 `context` | 读 `payload["context"]`，拼一句「用户正在看…」 |
| `onefeed/agent_runtime.py` build_agent | 系统提示固定 | 增可选 `focus` 参数，插在 INSTRUCTIONS 之后 |

---

## 14. 一句话

**把 Agent 从「信息流页的组件」变成「应用壳层的一层」，会话不随页面生死；详情页右栏就地接住上下文，历史与运行状态都由后端的线程/事件表兜底。** 这样「Agent 打开视频后自己消失」不是被补了一个按钮，而是从结构上不会再发生。

---

## 15. 附录：性能项（与本轮一起改）

同日做了界面性能审计，完整数据与证据见 `docs/perf-audit-2026-11-19.md`。结论与本文的批次直接咬合：

- **批次 A（先做，半天）**：顶栏去掉 `backdrop-blur`（`web/src/components/TopBar.tsx:43`，滚动最长帧 40ms→13.6ms）、`.page-shell` 的 `will-change` 改按需（`web/src/theme.css:117-118`，27ms→13.7ms）、TopBar 的 `onefeed:theme` 监听补依赖数组（`TopBar.tsx:32-36`）。这些先做，等于给后面的改动铺一层顺的地基。
- **批次 B（与 AgentProvider 同批）**：`/api/progress` 轮询只在字段变化时 setState；`Card` 加 `React.memo`；卡片外层的 `motion.div` 在 `layout=false` 时退回普通 `div`。这两件事都要动 `App.tsx` / `FeedPage.tsx`，和拆 Provider 一起改只需过一次回归。
- **批次 C（与详情页两列改造同批）**：`/api/media` 的 `cache-control` 从 `max-age=0` 放宽（`onefeed/api.py:741`，实测 `If-None-Match` 仍回 200 全量 153 KB）、封面走缩略图、头像不再拉 2048px 原图、后端 detail 加 60s 缓存（冷启实测 7.9s）。
- **批次 D（收尾）**：返回信息流不重复拉 feed（`web/src/api.ts:787-789`）、设置/详情/市场改路由级 `React.lazy`（可延后约 74 KB raw / 25 KB gzip）、`prefetched`/`feedCache` 加 LRU 上限。

