# 011 · Agent 原生应用：从「会搜」到「会做」

状态：P0 + P1 已落地（2026-11-18；T50 71 项、T51 50 项离线测试 + 真实模型 SSE 冒烟通过）；P2–P3 未开始
关联：006-ai（双引擎）、010-ai-agent（可回头的检索）、009-ai-summary（详情页总结）、003-host-app（刷新/进度）

## 1. 010 做完之后还差什么

010 把「一次盲搜」改成了「可回头的检索」，但产品形态没变：

```
用户一句话 → agent 查 3 次本地库 → Answer{reply, picks} → 几张卡片
```

它仍然是**一个更聪明的搜索框**。六个缺口：

| 缺口 | 具体表现 | 用户看到的 |
| --- | --- | --- |
| 不能操作应用 | 不会切平台、改排序、翻页、刷新、打开详情 | 想「只看 B 站」得自己点侧栏 |
| 不能多步 | 只会「搜 + 挑」，不会「挑完逐条总结再存起来」 | 「帮我总结这 3 条」做不到 |
| 不显过程 | 16–20s 同步 POST，回来只有一个结果 | 黑盒等待，像卡住了 |
| 不留状态 | items 表没有收藏/已读/隐藏 | 收藏按钮是死的 |
| 不主动 | 只能被问，不能自己跑 | 每天早上不会自己准备简报 |
| 结果少时不补救 | 只回 1 条也不解释、不放宽 | 截图里那种「就一条」 |

## 2. 判断：什么叫 Agent 原生

不是「接个大模型」，而是四件事同时成立：

1. **动作**：Agent 能调用应用自己的每个能力（有类型、有预览、有撤销），而不只是查库。
2. **过程**：每一步（想了什么、调了什么、拿到什么、动了哪里）都以事件流实时推给前端。
3. **状态**：动作的结果落库（收藏、已读、跑过的任务、线程历史），刷新页面还在。
4. **主动性**：Agent 可以按计划自己起一轮（每日简报），结果进站内收件箱。

### 「自主执行命令」的边界（必须先拍板）

**不做**：让模型生成 shell / 任意 HTTP / 前端 JS 并执行。

理由三条：
- 这是浏览器里的 Web 应用，后端和前端同机。任意命令 = 本地 RCE，一次幻觉就能 `rm -rf`。
- 任意 HTTP 出站 = SSRF + 把 API key 送出去，且无法审计。
- 不可测：脚本化测试无法覆盖无限命令空间，010 的 35 项离线测试会全部失效。

**要做**：**应用动作白名单**。整套业务能力就 14 个动作（见 §4），模型只能在这 14 个里选、参数被 schema 和 Python 侧双重校验。这已经是「完整的 Agent」，且每个动作可测、可撤销、可审计。

真要系统级命令，走**独立本地 MCP 桥**（opt-in、只读命令、独立进程），与本产品主链路解耦——不放进 011。

## 3. 三层架构

```
┌───────────── 前端 AgentConsole.tsx ─────────────┐
│ 指令输入 · 步骤轨迹（思考/工具/动作）· 结果卡 · │
│ 确认条 · 撤销 · 历史线程 · 定时简报收件箱       │
└───────────────────┬─────────────────────────────┘
                    │ SSE（run 事件流）
┌───────────────────▼─────────────────────────────┐
│ onefeed/agent_runtime.py   运行器                │
│ run_id · 预算（步数/秒/工具数）· 确认令牌 ·      │
│ 事件落库 · 断线重放 · 取消 · 失败降级            │
└───────────────────┬─────────────────────────────┘
                    │ 工具调用（pydantic-ai）
┌───────────────────▼─────────────────────────────┐
│ onefeed/actions.py   动作总线                    │
│ 注册表：name → (schema, level, run, undo)        │
│ 校验 → 权限分级 → 执行 → 审计行 → 可撤销         │
└───────────────────┬─────────────────────────────┘
                    │ 复用现有模块
       store.py / smart.py / summary.py / runner
```

- 010 的 `agent.py` 不推翻：`search_items / get_item / similar_items` 三个工具原样成为动作总线里的只读动作，`Answer` 扩一个 `actions` 字段。
- 旧 `chat()` 保留为降级路径（模型不可用 / 开关关闭 / 老前端），响应结构不变。

## 4. 动作清单（14 个，全部有 schema）

级别：L0 只读 · L1 纯 UI · L2 写本地状态 · L3 外部副作用（默认要确认）

| 动作 | 级别 | 参数 | 实现 | 撤销 |
| --- | --- | --- | --- | --- |
| `search_items` | L0 | terms/platforms/kinds/since/sort/limit/duration_*/like_min | store.search_items | — |
| `get_item` | L0 | id | store.get_item | — |
| `similar_items` | L0 | id/limit | store.cluster_items | — |
| `feed_stats` | L0 | platform? | store.count + smart.summary | — |
| `summarize_item`（P1） | L0→缓存 | id/force | summary.py + summaries 表 | — |
| `summarize_batch`（P1） | L0 | ids[] / style | 逐条 summarize + 合并 | — |
| `export_markdown`（P1） | L2 | ids[]/title | 写 .onefeed/exports/*.md，返回路径 | 删文件 |
| `ui_filter` | L1 | platforms/sort/since/keyword/kind | 事件推给前端，前端调 /api/feed | 恢复上一次筛选 |
| `ui_navigate` | L1 | page(feed/item/settings/market)/params | 前端路由 | 后退 |
| `ui_open_item` | L1 | id | 前端打开详情抽屉 | 关闭 |
| `ui_toast` | L1 | text/level | 前端提示 | — |
| `save_item` | L2 | id/on | item_marks 落库 | 反向写入 |
| `mark_read` | L2 | ids[]/state(read/hidden) | item_marks 落库 | 反向写入 |
| `refresh_feed` | L3 | platforms[] | 复用 runner.trigger + /progress 轮询，跑完自动续 | 不撤销，只报告结果 |

**关键设计**：
- 长动作（`refresh_feed`、`summarize_batch`）在工具内部就轮询到完成再返回，模型拿到的是「刷新完了，新增 12 条」，不是「已触发」。这样模型能接着干活（刷新→重新搜→挑→总结）。
- `ui_*` 动作**不阻塞**：返回 `{ok:true}` 同时把意图写进事件流，前端收到就执行；模型不必等前端。
- 每个动作执行后写一行审计（`agent_steps` 表），带 `undo_token`。

## 5. 运行器：事件协议

`POST /api/agent/runs` → `202 {run_id, thread_id}`，随后 `GET /api/agent/runs/{id}/events`（SSE）。

| 事件 | data | 前端行为 |
| --- | --- | --- |
| `run_start` | {run_id, input, model} | 开一个轨迹块 |
| `step` | {n, kind: think/tool/action/note, title, detail?} | 追加一行 |
| `tool` | {call_id, name, args_preview, ok, ms, result_preview} | 折叠行，可展开看参数与返回 |
| `action` | {kind: ui_filter/ui_navigate/ui_open_item/ui_toast, payload} | 立刻执行 UI |
| `need_confirm` | {confirm_id, action, summary, risk} | 弹确认条（允许/本次会话允许/拒绝） |
| `delta` | {text} | 打字机输出 reply |
| `done` | {answer, items, actions_applied, usage{steps,ms,tokens}} | 收尾，落库 |
| `error` | {message, fallback: "llm"/"rules"} | 显示错误并提示降级结果 |

SSE 细节：`id:` 用 step 序号，支持 `Last-Event-ID` 续传；心跳 15s；事件同时写 `agent_steps` 表，刷新页面用 `GET /api/agent/runs/{id}` 回放。

预算：`max_steps=12`、`max_seconds=90`、`max_tool_calls=10`（settings 可调）。超限不报错，发 `step: 预算用尽，先给你已完成的部分` + `done`。

## 6. 数据模型（SCHEMA_VERSION 4 → 5）

```sql
CREATE TABLE agent_threads (id TEXT PRIMARY KEY, title TEXT, created_at INTEGER, updated_at INTEGER);
CREATE TABLE agent_runs (
  id TEXT PRIMARY KEY, thread_id TEXT, status TEXT,          -- running/done/error/cancelled
  input TEXT, model TEXT, reply TEXT,
  steps INTEGER, ms INTEGER, tokens INTEGER,
  error TEXT, created_at INTEGER, finished_at INTEGER
);
CREATE TABLE agent_steps (                                   -- 事件流水，回放 + 审计
  run_id TEXT, seq INTEGER, kind TEXT, name TEXT,
  payload TEXT, undo_token TEXT, at INTEGER,
  PRIMARY KEY (run_id, seq)
);
CREATE TABLE item_marks (                                    -- 收藏/已读/隐藏
  item_id TEXT PRIMARY KEY, saved INTEGER DEFAULT 0,
  read_at INTEGER, hidden INTEGER DEFAULT 0, updated_at INTEGER
);
```

`item_marks` 用 `LEFT JOIN` 进 `_decode_row`，前端卡片多一个 state 字段；`page()/search_items()` 默认排除 `hidden=1`。

## 7. 安全与确认

- L0/L1 直接执行；L2 首次弹确认，可选「本次会话允许」；L3 每次确认（`refresh_feed` 会打外网、可能触发平台风控）。
- `confirm_id` 一次性、5 分钟过期、绑定 run_id，服务端校验，不做「前端说允许就允许」。
- 动作参数二次校验：平台/排序/kind 走 010 已有的 `_norm_*`，id 必须在最近一次候选或库里存在，路径类参数（export 文件名）白名单化。
- 审计：每条 L2/L3 动作落 `agent_steps`，可在设置页「Agent 活动」里看最近 50 条并撤销。
- 关闭开关：`settings.json {"ai_agent":false}` 或 `ONEFEED_AI_AGENT=0`，整体退回 006 旧路径。

## 8. 主动性：每日简报

`settings.json` 新增 `agent_briefing: {enabled, time:"08:00", platforms, topics}`。到点由后台线程起一个 headless run（同一运行器、无前端订阅），产出 `{title, digest, items}` 写入 `agent_runs`（status=done, thread="briefing"），前端收件箱角标提示。这是「Agent 原生」里唯一需要常驻的部分，用现成的 runner 线程池，不引 APScheduler。

## 9. 分阶段落地

| 阶段 | 内容 | 工作量 | 可验收的样子 |
| --- | --- | --- | --- |
| P0 垂直切片 ✅ | actions.py（11 个动作）+ runtime SSE + AgentConsole 轨迹 + save_item 落库 | 1 天 | 一句话 → 切筛选/刷新/挑 3 条/存起来，全程可见 |
| P1 长任务 ✅ | summarize_item/batch、export_markdown、设置页撤销入口、检索硬上限 | 1.5 天 | 「把这 3 条总结成简报存成 md」能跑完 |
| P2 记忆与主动 | item_marks 全量（已读/隐藏）+ prefs + 每日简报 + 收件箱 | 1 天 | 第二天早上有简报；「别给我看 X」生效 |
| P3 增强 | 同题聚合视图（cluster_id）、语义检索（本地 embedding）、语音输入 | 2 天+ | 「同一件事六个平台怎么说」 |

P0 先做**垂直切片**而不是「先把 14 个动作全写完」：切片打通 SSE + 轨迹 + 一个 L2 动作，后面动作只是往注册表里加行。

## 10. 验收标准

- **AC-1** 一句话触发 ≥2 类动作（读 + UI 或 读 + 写），轨迹里每步可见。
- **AC-2** 每个 L2 动作有审计行与 undo；撤销后 `item_marks` 回到原值。
- **AC-3** L3 动作未确认不执行；拒绝后 agent 说明「没刷新，用现有数据继续」并继续干活。
- **AC-4** SSE 首帧 < 300ms（run_start 立刻发），断开 30s 内重连能收到未读事件。
- **AC-5** 预算用尽时返回部分结果 + 明确说明，不抛 500。
- **AC-6** 刷新页面后历史 run 可回放（事件流从库里读）。
- **AC-7** 关掉 agent 开关，前端仍能走旧 chat，UI 不报错。
- **AC-8** 离线测试：FunctionModel 脚本化覆盖全部动作（每个动作 2 条断言起），SSE 契约测试，`test_ui_lint` 通过。

评测口径（人工 10 条指令）：任务完成率 ≥ 8/10；平均步数 ≤ 6；「结果少」时解释率 100%。

## 11. 与 010 的关系 / 回滚

- 010 的 `chat()`、`Answer`、`search_items`、开关全部保留；011 只**新增** `actions.py`、`agent_runtime.py`、SSE 路由和一张内存表。
- 回滚：删 `agent_runs` 路由 + 开关置 false，行为回到 010；数据表留着不影响旧路径。
- 依赖零新增（pydantic-ai 已有；SSE 用 `sse-starlette`？**不用**，用 FastAPI 自带 `StreamingResponse` 手写 15 行，避免新依赖）。

## 12. 不做（明确出界）

- 任意 shell / 任意 HTTP / 模型生成前端代码执行。
- 自动发评论、自动登录、自动投稿（涉平台风控与账号安全，任何时候不做）。
- 云端托管 agent（保持本地、单用户、无账号体系）。

## 13. P0 实现记录（2026-11-18）

### 已交付

| 层 | 文件 | 内容 |
| --- | --- | --- |
| 存储 | `onefeed/store.py` | SCHEMA v5：agent_threads / agent_runs / agent_steps / item_marks；`page()/search_items()/get_item()` LEFT JOIN 标记列，hidden 默认不进流；ensure_thread / start_agent_run / finish_agent_run / add_agent_step / get_agent_run / recent_agent_runs / get_mark / mark_item / saved_items |
| 动作 | `onefeed/actions.py` | P0 11 个动作（L0 4 / L1 4 / L2 2 / L3 1），P1 补齐 summarize_item / summarize_batch / export_markdown（共 14）；call() 做类型归一化、L3 未确认抛 ConfirmRequired、结果带 _ms；apply_undo() 支持 mark / marks / export |
| 运行器 | `onefeed/agent_runtime.py` | start/run 生命周期、预算（12 步 / 120s / 10 次工具，其中检索类最多 4 次）、need_confirm 等待与放行（不超过本轮 deadline）、取消、事件写库、SSE（首帧 retry + 15s 心跳 + Last-Event-ID）、_hints() 把 smart.parse_query 读出的条件贴进 prompt |
| API | `onefeed/api.py` | POST /agent/runs（202）、GET /agent/runs/{id}/events（SSE）、GET /agent/runs/{id}（回放）、confirm / cancel、GET /agent/runs、GET /agent/actions、POST /agent/undo、GET /agent/saved、POST /agent/mark |
| 前端 | `web/src/api.ts`、`web/src/components/AgentConsole.tsx`、`AiDock.tsx` | agentStart/agentStream/agentConfirm/agentCancel/agentMark/agentSaved/agentUndo/agentReplay；轨迹（step/tool/action/need_confirm/error）；done 直接用 SSE 里的 items，不再二次请求；ui_filter/ui_open_item 驱动 feed 与详情；409 回落到旧 chat |
| 测试 | `tests/test_agent_runtime.py`、`tests/test_agent_tasks.py` | T50 共 71 项（含检索硬上限）：v5 迁移、动作 schema、归一化、undo、L3 确认、FakeRunner 刷新增量、脚本模型多步、幽灵 id 丢弃、预算、模型异常、HTTP 全路由、SSE 续传、回放一致、plan.since 透传；T51 共 50 项：14 动作注册、总结缓存与 force、批量截断与跳过、导出 md 内容/撤销/越界保护、FunctionModel 三步、活动列表 events |

真实模型冒烟（本地库 800+ 条，问题「今天 B 站有哪些 AI 相关内容值得看的」）：`202 → 20–25 个事件（run_start/think/feed_stats/3–5×search_items/get_item/ui_filter/delta/done）→ done 带 7–8 条与 plan → GET 回放事件数与实时一致`，单轮 18–29s。

### 与方案的差异

- P0 只上 11 个动作：summarize_item / summarize_batch / export_markdown 在 P1 补齐（现共 14 个）。
- P0 就把 mark_read（已读/隐藏）一起做了；确认条只做了 L3 必需形态（允许 / 不用），「本次会话允许」与线程历史 UI 留 P1。
- 预算默认值从 010 的 6 改为 10，与 §5 一致（010 spec 里的 6 是历史值）。
- plan.since 取「最近一次带时间条件的检索」：模型中途放宽到不限时就是 0，不假装还在按今天筛；前端只在 since 落在 36h 内时显示「今天」。
- plan.keyword 只给第一个词：前端「用这个条件刷」仍走旧单子串 LIKE，拼一串必然 0 条。

### 验收标准状态

- AC-1 ✅ 真实一轮里出现检索 + UI 动作两类，轨迹每步可见。
- AC-2 ✅ save_item / mark_read / export_markdown 都带 audit 行与 undo_token；T50 断言标记撤销后回原值，T51 断言导出撤销真删文件、越界 token 不删。
- AC-3 ✅ 未确认 ConfirmRequired；确认后 FakeRunner 返回增量；拒绝路径由 T50 覆盖。
- AC-4 ✅ start() 先落 run_start 再起线程（T50 断言返回前已落库）；断线重连按 Last-Event-ID。
- AC-5 ✅ 预算用尽发 budget note + 部分结果 + done，不抛 500。
- AC-6 ✅ 回放与实时同源（agent_steps），T50 断言事件数一致。
- AC-7 ✅ 关开关走旧 chat，前端 409 回落，不 import pydantic_ai。
- AC-8 ✅ T50 71 项 + T51 50 项 + test_ui_lint 通过；全量离线 18 组全过。

### 已知遗留（P1）

- ~~每次超预算都会追加一条 budget note~~ 已修：模型连着重试也只提示一次。
- 「本次会话允许」（一次确认放行同类动作）与线程历史 UI 仍未做。
- 每日简报、prefs、同题聚合、语义检索未做（P2–P3）。


## 14. P1 实现记录（2026-11-18）

### 新增动作（三个，动作表补齐到 14 个）

| 动作 | 级别 | 参数 | 行为 |
| --- | --- | --- | --- |
| `summarize_item` | L0→缓存 | id / force | 先读 `summaries` 表，命中且 tldr 非空直接回；否则 `summary_mod.build()` 后写回。模型不可用时 summary.py 自身 `_rule_summary` 兜底，不抛。 |
| `summarize_batch` | L0 | ids[]（≤6）/ style（brief/outline）/ budget_sec（5–70，默认 55） | 顺序逐条总结；过了 deadline 的条目进 `skipped[{id,error}]` 而不是让整批失败；返回 summaries / count / skipped。 |
| `export_markdown` | L2 | ids[]（≤8）/ title / style / budget_sec | 逐条总结后渲染 md 写 `.onefeed/exports/<YYYYmmdd-HHMMSS>-<slug>.md`，返回 path / count / bytes / skipped；undo_token = `{kind:"export", path:…}`。 |

导出目录取 `Path(store.path).parent / "exports"`（`Ctx.exports_dir` 由 runtime 注入）。`apply_undo` 的 export 分支会把目标 `resolve()` 后校验 `parent == exports root` 且后缀 `.md`，越界或非 md 一律拒绝——撤销接口不接任意路径删除。

### 行为修复（真模型冒烟逼出来的）

1. **确认等待吃穿总预算**：模型在总结完之后自作主张调 `refresh_feed`，need_confirm 干等 60s，撞 90s 上限整轮降级。→ `Deps.deadline` 记录本轮硬截止，`_await_confirm` 的等待取 `min(timeout, deadline - now - 10s)`。
2. **检索把动作预算花光**：8 次 search/get 用掉 10 次额度，等要 export 时已无预算。→ 两道闸：instructions 里写死「检索类加起来最多 4 次」，`_run_action` 里 `MAX_SEARCHES = 4` 确定性拦截（第 5 次起回 ok=False 与「用已拿到的做正事」，轨迹里留一条「检索够了，先用手上这些」的 note）。
3. **预算从 90s 提到 120s**：单条真实总结 15s 上下，两条 + 导出在 90s 里太紧。
4. **steps 双计数**：P0 遗留在锁内锁外各加一次 `deps.calls`，轨迹上 2 次工具显示成 4。已删锁外那行。
5. **`summary.build(host=None)` 崩**：`host.summary_source` 无条件调用，异常文本会写进 caveat。→ 先判 `host is not None`。

### 撤销入口（设置页）

`GET /api/agent/runs?events=1` 带回每轮的事件流水，设置页新增「Agent 活动」段：最近 8 轮的时间、输入、状态、回复，以及每个带 `undo_token` 的动作一条按钮（撤销收藏 / 撤销标记 / 删掉导出的文件）。点击走 `POST /api/agent/undo`，成功后刷新列表与全局数据。默认请求不带事件（一轮几十条），只有这个页面显式要。

### 真模型冒烟（问题：「挑两条今天 B 站讲 AI 的视频，各写一句总结，然后导出成一份 md 简报」）

`steps=7 · 29.6s · tokens 64955 · actions=[summarize_batch, export_markdown]`，产出 35 行 md（`#` 标题、生成时间、每条的小标题/平台/原链接/要点），action 事件带 export token，reply 里给出路径。同题前两轮分别以「确认超时」和「检索用满预算」失败，是本轮两处修复的来源。

### 仍未做

- 确认条「本次会话允许」一次放行同类动作（现在每次 L3 都要点一次）。
- 线程历史 UI（多轮对话的左侧列表）；现在只有活动列表。
- 每日简报、prefs 记忆、同题聚合、语义检索（P2–P3）。
- 批量总结是串行的：6 条最坏约 90s，靠 budget_sec 截断而不是并发。并发会打满模型供应商的 RPM，暂不做。
