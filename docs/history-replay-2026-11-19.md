# 历史回放丢结果卡片：根因与修复（2026-11-19）

## 现象

在「最近的对话」里点开昨天那段「帮我找一条 B 站讲 AI 的视频」，回来的只有两行字：

> 今天 B 站 AI 相关只有 3 条，最值得看的是 AOCI 项目索引 那期（1273 赞），已帮你打开……

原来那几条结果卡片、计划清单、「用这个条件刷」按钮全都不见了，看着像 Agent 把视频弄丢了。

## 根因

数据没丢，是回放只读了一半的数据源。

1. 一轮对话的完整结果在 `done` 事件的 payload 里（`items` / `plan` / `suggestions` /
   `understood` / `usage`）。每个事件都由 `EventWriter.emit` 落进 `agent_steps`
   （`onefeed/agent_runtime.py:146-160`），所以卡片一直在库里。
2. 但 `GET /api/agent/threads/{id}` 走的是 `store.thread_runs()`，它只 `SELECT id, input,
   reply, status, steps, ms, error, created_at, finished_at`（`onefeed/store.py:645-652`），
   没有把该 run 的事件读出来。
3. 前端 `resumeThread` 拿到这些字段后只铺 `input` / `reply` 两行文本
   （`web/src/agent/AgentProvider.tsx:520-529`），于是结果卡片、轨迹、计划一起消失。

同一份数据在另外两个接口里本来就是读出来的（`get_agent_run(steps=True)`、
`recent_agent_runs(steps=True)`），只有线程回放漏了——所以是接口契约不一致，不是能力缺失。

真库核对（8 轮全部 `status=done`）：8177adc0 的 `items=3`、dd034dbd 的 `items=8`、
a95c2f42 的 `items=3`、1fa4fc15 / 17687747 的 `items=2`、9af48c2a 的 `items=1`、
814c7d1d 的 `items=3`。一条都没少。

## 修法

### 后端：线程详情默认带事件流

- `onefeed/store.py:645-666`：`thread_runs(thread_id, limit, steps=True)`，在 `steps=True`
  时按 `run_id` 查 `agent_steps`，用现成的 `_decode_step()` 解成 `run["events"]`，
  与 `recent_agent_runs` 完全同形。
- `onefeed/api.py:329-341`：`GET /api/agent/threads/{id}` 增 `events: bool = Query(True)`，
  透传给 store。只要文本列表就传 `?events=0`。

### 前端：回放与实时同形

- `web/src/api.ts`：`AgentThreadRun` 增 `events?: AgentEvent[]` 与 `steps` / `ms`。
- `web/src/agent/AgentProvider.tsx`：
  - `AgentTurn` 增 `history?: boolean`；
  - `resumeThread` 对每一轮取最后一条 `done` / `cancelled` 事件，用与实时 `settle()`
    完全相同的字段组装 `AiResponse`（items / count / suggestions / understood / steps / ms），
    轨迹照铺但滤掉 `delta`（几十帧流式正文没有回放价值），`stopped` 由 run 状态与事件类型判定；
  - 历史里带 `saved` 的结果条目顺手并进 `saved` 集合，星标一开始就是实心的。
- `web/src/agent/AgentThread.tsx`：轨迹传 `readonly={turn.history}`。
- `web/src/components/AgentConsole.tsx`：新增 `readonly`。历史里的旧确认 / 旧问卷不再渲染成
  可点按钮（那时已经结束了），改为「这轮没等到你的确认 / 回答」；空轨迹也不再显示「正在想…」
  转圈——历史不会继续想。

## 验证

- `GET /api/agent/threads/{id}`：最近一轮 `events=10 items=1`，`done` 里 `items` 完整。
- 浏览器（playwright + Chrome 1280×900，服务 8799，924 条真实数据）：`/agent` 左栏点开
  「帮我找一条 B 站讲 AI 的视频…」→ 2 段对话、1 张结果卡、「打算这么做」三条计划、
  理解指令 / 检索 / 打开详情轨迹齐全；点卡片直接进
  `/item/bilibili%3Avideo%3ABV1DwsK6aE5R`，跟实时那一轮一模一样。截图
  `.onefeed/tmp/shot-history-replay.png`。
- 回归：`tests/test_agent_runtime.py` 增 5 条（默认带事件、done 里有 items、`steps=False`
  不带、HTTP 默认带、`?events=0` 不带）；`tests/test_interaction.py` 增 1 条静态守门
  （回放读 done/cancelled、滤 delta、readonly 贯通、类型上有 events）。
- `uv run --with pytest python -m pytest tests -q` → 67 passed；
  `node scripts/check-ui.mjs` → 无违规；`npm run build` → index-C-_-dYtB.js 439.72 kB。

## 仍然欠的

- 回放没有轮次分隔与时间戳（现在靠消息间距区分），历史里也看不出「哪一轮触发了页面跳转」。
- 线程不能重命名 / 删除 / 搜索；20 条以上只能靠时间。
- 运行中的 run 在历史里没有「进行中」标记，点开会显示空白（事件还没收尾）。
