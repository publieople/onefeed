# Agent 过程收起、详情页右栏与触底自动检查（2026-11-25）

这一轮修三处交互：Agent 跑完还摊着一屏过程；详情页点「打开 Agent」会从主页底栏的胶囊横穿过来；信息流滑到底既不自动取新内容，也不告诉人它在干什么。

## 1. 跑完的一轮，过程默认收起

改动在 `web/src/agent/AgentThread.tsx`。

以前 `turn.trace` 直接铺在结果之前，一轮十几步，真正的回答被挤到屏幕外。现在完成后只留一行折叠按钮，文案是「过程 4 步 · 12.1s」；点开才渲染 `AgentConsole`，展开的仍是同一份事件，不是另做一份摘要。

- 组件：`TraceDisclosure({ events, answered, answeredAsk, readonly, ms })`，`useState(false)` 默认收起。
- 位置：结果卡和推荐动作之后，过程在最后一行，第一眼看到的是答案。
- 守门：`data-agent-trace="collapsed"` 标出状态；`aria-expanded` 跟按钮同步；历史回放仍传 `readonly`，旧确认/旧问卷不会重新变成可点按钮。
- 运行中不折：正在跑的一轮仍展开过程 + 骨架 + 停止按钮，用户要看它卡在哪一步。只有结束（含取消/失败）才折。

## 2. 详情页的 Agent 从右缘长出来

改动在 `web/src/agent/AgentProvider.tsx`。

`openWith` 原来不分页面，一律 `createGhost({ agent: "pill" })` + `runNav("tab")`，拿主页底栏胶囊当转场起点。详情页没有那颗胶囊，于是演成「底栏横穿整页飞到右边」。现在：

```
if (onItemPage) {
  setOpen(true);
  window.setTimeout(() => inputRef.current?.focus(), 30);
  return;
}
```

右栏自己用 Shell 的宽度补间（钉住时 0→320）或抽屉滑入（窄屏）完成转场，不再造 ghost。`close` 同样在详情页直接 `setOpen(false)`，不缩回胶囊。主页的唤起器转场原样保留。

## 3. 滚到底自动检查，并在底部说话

### 后端

`onefeed/service.py` 的 source 白名单从 `agent | user` 扩成 `agent | auto | user`；`onefeed/api.py` 的 `POST /api/refresh` 把请求体里的 `source` 透传给 `RefreshRunner.trigger`。未知来源仍落回 `user`，前端只认三类。

### 前端

App 轮询多了一条 `source === "auto"` 分支：不动顶栏进度、不换 `reloadKey`、不触发刷新演出，只更新 `autoRunning / autoProgress / autoResult`，完成后 `autoKey + 1`。

`useFeed(query, reloadKey, autoKey)` 收到 `autoKey` 变化时走 `merge()`：从首屏往后翻，直到碰见合并前就有的条目（最多 8 页），把整段新增并到最前面，页内也按 id 去重；已加载的分页和 `next` 原样留着。`FeedPage` 在 layout effect 里按 `scrollHeight` 高度差补回滚动位置，人正看着的卡不会被上面插进来的新卡顶走。

以前的 `merge()` 只 GET 一页（18 条）：一轮新增 53 条时，第 19 条以后永远进不了列表，底部却写着「看看新增的 53 条」。现在按旧 id 边界继续翻页，整段新增都能接住。

触发条件（`FeedPage` 底部传感器）：

- 必须真滚过（`scrollY > 120`），短文列表不会一进来就打平台；
- 没有下一页、首屏已加载、当前没有刷新/自动检查在跑；
- 触底后再等 600ms，避开惯性滚动；
- 同一页 10 分钟内只自动跑一次；用户手点刷新或 Agent 正在抓时让位，409 让位不消耗这 10 分钟。

界面反馈都在底部状态条上：

- 运行中：旋转图标 +「正在看看有没有新内容… 3/7」+ 3px 细进度条；
- 合并中：「正在把新内容放进来…」；
- 完成：「自动检查完：新增 53 条」或「自动检查完：这轮没有新内容」，有失败/冷却再追加「· N 个平台没抓到」「· N 个平台冷却中」；
- 失败：显示「自动检查没成功：…」并在旁边给「重试」按钮；网络/接口失败会复位 10 分钟节流，不会锁死；
- 有新增时给一个「看看新增的 N 条」按钮，点了回到顶部。

手点刷新或失败重试撞上自动检查的 409 时，不再静默：提示「自动检查正在跑，等它跑完再刷新 / 再重试」。顶栏进度件结束后也会读 `phase` 和 `next_at`：全部冷却显示「都在冷却 · 最早 N 秒后」，全失败显示「都没抓到」，不再一律念成「没有新增 抓完了」。

自动检查只查当前筛选的平台：筛了 V2EX 就发 `{ source: "auto", platforms: ["v2ex"] }`，新增数才对得上这一屏；不筛才是全平台。

## 验证

- `cd web && npm run build`：`index-Q3hrflW9.js` 480.39 kB / gzip 152.56 kB，`index-DUGfbJN7.css` 58.55 kB。
- `uv run python tests/run_all.py`：32 项全绿。
- 新增守门：`test_interaction.py` 的 `test_finished_agent_turn_collapses_its_trace`、`test_item_page_agent_opens_from_the_rail_not_the_pill`；`test_refresh_playout.py` 的 `test_scroll_bottom_checks_auto_and_says_so`、`test_auto_failure_can_retry_and_manual_refresh_explains_busy`；`test_refresh.py` 的 `test_auto_source_is_kept_and_unknown_falls_back_to_user`。
- 真机（127.0.0.1:8787，ego/DSH 浏览器）：
  - `?p=v2ex&q=deepseek` 滑到底，底部出现「正在看看有没有新内容… 1/1」；结束显示「自动检查完：这轮没有新内容」。说明自动检查确实只查 V2EX。
  - 未筛选时同一入口跑全平台，显示「正在看看有没有新内容… 1/7」到 7/7，结束显示新增数与冷却平台。
  - V2EX 筛选下触底自动检查显示「新增 6 条」，顶栏计数从 1771 跟到 1777，底部出现「看看新增的 6 条」。
  - 全平台强制刷新一轮拿到 `new_total=54`；紧接着再发一次普通刷新，后端返回 `phase=empty`、七个平台全 `skipped`，顶栏显示「都在冷却 最早 30 秒后」，不再是「没有新增 抓完了」。
  - 详情页点「打开 Agent」，右栏从右缘展开，没有底栏胶囊横穿；问「这条讲了什么」跑完，结果下方只留「过程 4 步 · 12.1s」折叠行。

## 已知边界

- 自动检查是「看一眼」，不是完整刷新：只把新增段并到已加载列表前面，更早的分页不重排；要看完整新排序还是手点刷新。合并最多翻 8 页，避免异常数据把整屏翻空。
- 10 分钟节流按页面会话记，刷新页面就重置；不做跨标签页共享。
- 自动检查的结果条会在切换筛选后继续显示上一轮的数字，直到下一次自动检查覆盖；不影响内容，但数字可能对不上新筛选（后续要清就挂在 query 变化上）。
- 详情页右栏的转场交给 Shell 的宽度补间，窄屏抽屉走自己的 translate；两者都不再经过 View Transition。
