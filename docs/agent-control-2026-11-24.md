# 采集归谁管、Agent 怎么抓、会话怎么切（2026-11-24）

这一轮把「采集」从信息流的一个附属动作，拆成了三个独立对象：用户刷新（RefreshRunner）、Agent 自己抓的一轮（同一条 runner，不同 source/owner）、以及顶栏那枚采集胶囊（健康状态）。三者共用一套状态，但谁也不能劫持谁。

## 1. 七条决策

1. 停止回答时连采集一起停。
2. Agent 抓取只在 Agent 窗口显示，主窗口不刷新。
3. 抓不抓由模型判断；用户发起的问题搜到 0 条，Agent 必须自己抓一轮再交代。
4. 允许运行中切会话；切走后后台继续跑，切回来能继续看。
5. 平台失败/长期未更新常驻顶栏采集胶囊，浮层里可重试。
6. 设置未保存时站内离开弹三选：保存 / 不保存 / 取消。
7. 详情页的 ItemChat 与全局 Agent 合并成一个入口。

## 2. 采集的来源与取消

### 2.1 状态字段

`onefeed/service.py` 的 `RefreshRunner._state` 增四个字段：

- `source`：`"user"` 或 `"agent"`。
- `owner`：Agent 的 run_id；用户手点为 `""`。
- `cancel_requested`：叫停信号，不立刻终止线程。
- `cancelled`：这一轮被叫停、没实际抓的平台数。

`trigger(platforms=None, warmup=False, force=False, source="user", owner="") -> tuple[bool, dict]`，线程 `_run(active, warmup, source, owner)`。

### 2.2 取消语义

`cancel(owner=None) -> bool`：

- 没在跑直接 False。
- 带 `owner` 时必须等于当前轮的 owner；owner 为空的用户轮，Agent 的停止不能顺手停掉它。
- 命中后置 `cancel_requested=True`，并把所有还在 `queued` 的平台改成 `status="cancelled"`。
- `_run` 循环每轮先看 `stopped or status != "queued"`；叫停时跳过 prune/cluster，收尾补 `cancelled` 计数，`phase="cancelled"`，`done` 含 cancelled。

Agent 侧 `RunState` 增 `runner` 引用；`RunState.cancel(run_id)` 除了置 `cancel` 标志，还调 `runner.cancel(owner=run_id)`。前端「停止这一轮」因此不只是停 SSE，而是真的把采集线程叫停。

### 2.3 pull 事件

`onefeed/actions.py` 新增 `_pull_event(snap, source, added, status="")`，从 runner 快照生成一帧给 Agent 窗口的事件：

- `title`：正在抓 {current} {done}/{total} / 已停止，剩下的平台不抓了 / 这一轮没有实际抓取 / 这一轮没抓成 / 抓完了，新增 N 条。
- `status` 优先级：显式 status > running > cancelled > empty > done。
- 字段：`title/status/phase/done/total/added/current/source/cancelled/error`。

`pull_feed(ctx, platforms=None, timeout=None, announce=True, source="user", owner="", should_stop=None)` 每 1.0 秒且 owner 非空发一帧 `ctx.send("pull","pull_feed",…)`，结束后再发一帧；`should_stop` 命中时调 `runner.cancel(owner=owner or None)` 并发 cancelled 帧。

## 3. Agent 自己抓：模型决定，运行器上闸

### 3.1 工具

新增 `pull_feed` 动作，L3（会打外网）但 `needs_confirm=False`——它是 Agent 内部动作，不该弹用户确认。`act_pull_feed` 从 `ctx.run_id` 取 owner，`announce=False`，超时用 `ctx.refresh_timeout`。

原来的 `refresh_feed` 保留，仍是 L3 + 需确认，语义收窄为「用户明确要求刷新时用」。

### 3.2 每轮三道闸

`_run_action` 在执行 `pull_feed` 前检查：

1. 设置 `agent_auto_pull` 关掉 →「设置里关掉了 Agent 主动抓取，先用现有结果回答」。
2. `ctx.runner is None` →「刷新组件不在，抓不了」。
3. 本轮已抓过（`deps.pulled`）→「这一轮已经抓过一次了…」。
4. 剩余时间 < `AUTO_PULL_MIN_SECONDS=30.0` →「这轮剩余时间不够抓一轮了…」。

通过则 `deps.pulled=True`，`ctx.refresh_timeout = max(10.0, min(50.0, remaining - 20.0))`。

### 3.3 提示词

`INSTRUCTIONS` 改成：库里没有就用 `pull_feed` 去抓；每轮最多一次；抓完再搜；仍 0 条就直说没有，别硬凑。删掉了 `search_items` 返回 0 时运行器确定性接管的老逻辑（`_auto_pull` 整函数移除）。

## 4. 主窗口不被 Agent 抓取带动

`App.tsx` 轮询 /api/progress 时先看 `data.state.source`：

- 是 `"agent"`：`agentPulling.current = running`，`wasRunning.current = false`，直接 return，不改 `progress`、不 `reloadKey++`、不 `refreshSeq++`、不弹 toast。
- 否则清掉标记，走原逻辑。

用户这时点刷新，后端返回 `refresh_running`，前端提示「Agent 正在抓一轮，等它跑完再刷新」，而不是两个线程抢插件。

Agent 窗口侧，`AgentConsole` 新增 `PullRow`：只取最后一帧 `kind="pull"`（避免每秒一行），显示旋转/成功/失败图标、标题、进度条，右侧「Agent 自己抓的」。

## 5. 每线程会话

`AgentProvider.tsx` 从「一个全局 turns/live」改成「每个 threadId 一份 SessionCore」：

- `sessions: Record<string, {turns,busy,live,answered,answeredAsk,stopping,threadId,error}>`，另有 `streamsRef: Map<string,StreamCtl>`。
- `ask` 固定写当前 key；`settle`/`listen`/`fallback` 都带 key，后台线程的结果只写它自己的 session。
- `applyUi` 首行 `if (key !== activeKeyRef.current) return`——后台线程的 ui_open_item 不劫持前台。
- `resumeThread`：内存里已有该线程就直接切，不拿服务端历史覆盖正在跑的 turns。
- `stop` 只停当前线程；8 秒兜底只收 UI。
- `newThread` 生成新 id、建空白 session；运行中切走不打断。
- 历史列表用 `Object.keys(sessions).filter(k => sessions[k]?.busy)` 得到 `running`，AgentPage 在标题与「N 轮」之间渲染一枚 `h-1.5 w-1.5 animate-pulse rounded-full bg-accent`，title/aria「后台还在跑」。

已知边界：新会话第一轮还没进 historyItems 时列表上没有这一项，所以看不到点；刷新页面后内存里的后台轮次也会丢（服务端仍可查历史，但不会自动重连）。

## 6. 顶栏采集胶囊

`/api/health` 的 `platforms` 每行现在有：`platform,label,count,last_fetched_at,last_run_at,last_ok_at,last_ok,failed,interrupted,stale,available,interval,state,error,note,running`，另有顶层 `plugin_errors` 与 `needs_attention`。

`_platform_health()` 的判定：

- `failed`：最近一次 run 失败，且晚于最近一次成功。
- `interrupted`：状态为空且跑了超过 600 秒。
- `stale`：最近成功距今超过 `max(24h, interval*6)`。
- `unavailable`：插件发现失败。
- 优先级 unavailable > failed > stale > ok。
- 装了但从未抓过且库里没内容的插件不进行，避免顶栏一开始就一堆红点。

`CollectPill.tsx`：有 attention 时圆点变红、显示 `AlertTriangle` + 数字；浮层按「失败/不可用 → 久未更新 → 其余按时间」排序，行尾 `RotateCw` 只对 `available && (failed||stale)` 显示，点击 `onRetry([platform])`；底部列 `plugin_errors` 第一条，以及「重试 N 个」。

平台名兜底：`nameOf(p) = p.label && p.label !== p.platform ? p.label : platform(p.platform).label`。B 站插件读不动时后端 label 就是 `"bilibili"`，没有这层会显示成英文 id。

## 7. 设置未保存三选

`components/ui/Confirm.tsx` 新增 `choiceDialog(opts): Promise<"confirm"|"secondary"|"cancel">`，`ConfirmOptions` 增 `secondaryText`。原来的 `confirmDialog` 变成它的布尔包装，调用方不用改。

`SettingsPage.tsx`：

- `saveSettings` 改成返回 `Promise<boolean>`。
- `askLeave(to)`：只有 dirty 才问；三键「保存并离开 / 不保存 / 取消」。保存失败留在原地；不保存直接走；取消什么都不做。
- 站内链接：dirty 时在 document 捕获阶段拦 `a[href]`，跳过新窗口/下载/外站/同 path+search，`preventDefault + stopPropagation` 后交给 `askLeave`。
- 浏览器返回：dirty 时压一个 `__ofSettingsGuard` 哨兵，popstate 时用哨兵吃掉一次返回，再弹三选；确认离开后 `history.go(-(guardDepth+1))`，700ms 后仍在 /settings 就兜底 `navigate("/")`。

## 8. 合并 AI 入口

`ItemPage.tsx` 不再渲染 `<ItemChat/>`，改成内联「问问这条」区块：三个 starter 与「打开 Agent」全部调 `useAgentActions().openWith(text)`，打开右侧全局 Agent 抽屉，并把这句话预填进输入框。上下文由全局 Agent 通过 `itemId` 自己取，不再单独维护一条 item chat 流。

## 9. 验证

- `uv run python tests/run_all.py`：31 项全绿。新增 `test_refresh.py::test_cancel_stops_queued_platforms`，覆盖「错 owner 拒停、对 owner 停掉排队平台、phase=cancelled、cancelled 计数」。
- `cd web && npm run build`：index-D6FavYId.js 472.17 kB / gzip 150.06 kB，index-DDBIYDwj.css 57.52 kB。
- 真机（本机 8787，真实七平台）：
  - Agent 问「拓扑绝缘体…」触发 pull，Agent 窗口显示「正在抓 小红书 3/6」，主窗口顶栏没有进度胶囊、没有 reload。
  - pull 到 3/6 时切历史线程再切回，pull 仍在跑；历史项旁边有琥珀脉冲点。
  - 问「量子点显示技术…」时点停止，1.8 秒后按钮变「抓取还没跑完，交给后台继续」，`/api/progress` 为 `phase=cancelled, cancel_requested=true`，说明取消穿透到 runner。
  - 采集胶囊显示「1 个平台需要看一眼：B 站」，浮层里 B 站「插件读不动」、其余六平台正常，失败平台可单行重试。
  - 设置页改值后点「插件市场」，弹「这些设置还没保存」；取消留在原地且值保留，不保存回滚到旧值，保存并离开写入后端。
  - 详情页点「最值得记住的是哪一点」，右侧 Agent 抽屉带着这句话打开。

## 10. 已知边界

- bilibili 插件目录 `onefeed-plugins\plugins\bilibili` 在 Windows 层 `[WinError 5] 拒绝访问`，当前只能显示「插件读不动」，重试按钮对它不出现。这是环境问题，需要重启后重装插件。
- 刷新页面会丢失内存中的后台轮次（服务端历史还在，但不会自动重连正在跑的流）。
- 前端 `ItemChat.tsx` 与 `streamItemChat` 客户端已删除；后端 `POST /item/{id}/chat/stream` 保留为独立 API（`tests/test_summary_depth.py` 仍覆盖），只是 UI 不再调用。
