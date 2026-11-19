# 四条反馈落地记录（2026-11-19）

这一轮只做用户提的四件事，外加把「能交互的 Agent」从演示级推到可用的垂直切片。

## 1. 转场：冷卡片没有缩放动画

**现象**：点没打开过的卡片，只有整页淡出；点打开过的才有共享元素缩放。

**根因**（不是缓存命中玄学，是悬停预取）：`Card` 在 `onPointerEnter` 起 260ms 定时器预取
`/api/item/{id}` 与 detail。预取过的条目进详情首屏就有标题与媒体框；没预取的条目首屏是
骨架，而骨架里没有 `[data-vt=media]` 和 h1，新快照缺共享元素，View Transition 退化成
根节点淡出。

**修法**：卡片把 `item` 快照塞进 navigate state（`web/src/pages/FeedPage.tsx`），详情页
`seedData()` 优先用 peek 结果、其次用 state 里的快照垫首屏（`web/src/pages/ItemPage.tsx`）。
共享元素不再取决于预取时机。

**证据**：`.onefeed/tmp/probe_vt_call.py` 在 `document.startViewTransition` 的 update 回调里
查 DOM：冷卡片 juejin 文章 `calls=1 hadH1=True hadTitleName=True`；冷卡片 B 站视频
`hadMedia=True mediaBox=[860,484]`。本机 playwright 的 visibilityState 是 visible，动画真的跑。

## 2. AI 总结「等几秒后瞬间弹出」

**根因有两层**：
1. 模型先吐 reasoning，首字要 3–7s（MiniMax 关不掉思维链：`thinking:{type:"disabled"}`
   直接 400，`enable_thinking:false` 仍吐 reasoning；砍 max_tokens 会让正文为空）；
2. 缓存命中路径只发 `done` 不发 `delta`，前端收到整篇直接上屏。

**修法**：
- 后端缓存命中先发 `status/writing`，再用 `_cache_chunks()` 把结构化小结拼回行协议文本分块发
  `delta`（`onefeed/api.py`）；
- 前端打字机：`setInterval(50ms)`、速率 `max(60, backlog/1.6)` 字/秒，用真实 dt 累计（不用 rAF，
  标签页不可见时 rAF 会被节流到近乎停摆）；`onDelta` 同步维护 `rawRef`，`onDone` 只写 pending，
  等铺完再 promote（`web/src/pages/ItemPage.tsx`）。

**证据**：缓存条目文字 207→218→228→242→257→305 逐帧增长，约 1.2s 铺完；未缓存条目
0.29s 出现「Agent 正在通读素材…」骨架，4.77s 后 134→…→276 逐字增长。

## 3. 关键词：Ctrl+K 被浏览器抢走

**修法**：主键改为 `/`（单键，且不在输入框里触发），辅键换成 `Ctrl/⌘ + Shift + K`；
`AiDock` 收到 `onefeed:ask` 后 `setOpen(true)` 并 `inputRef.focus()`。
快捷键帮助表同步（`web/src/components/ShortcutHelp.tsx`）。

**证据**：`.onefeed/tmp/probe_keys.py` —— `/` 与 `Control+Shift+K` 都能让
`[role=dialog]` 出现，且 `document.activeElement` 的 aria-label 是「向 OneFeed 提问」；
Esc 关闭后焦点仍在输入框。

## 4. 底部 AI 从「搜索框」变成能交互的 Agent

### 4.1 会先问一句（ask_user）
- 后端 `onefeed/actions.py` 新增 `TALK_ACTIONS`：`set_plan` 与 `ask_user`（不写 REGISTRY，
  `catalog()` 里追加，设置页也看得到）；`agent_runtime._await_answer()` 发 `need_answer` 事件并
  阻塞等答复（受 deadline−10s 约束），`resolve_answer()` 由 `POST /api/agent/runs/{id}/answer`
  唤醒；超时就按最合理的默认继续，并在 reply 里说明假设。
- 前端 `AgentConsole` 的 `AskRow`：问题 + 选项胶囊 + 直接回一句。**单选点一下即发送**
  （点两次才算答完太笨），多选留「就这个」。

### 4.2 先说打算怎么做（set_plan）
- 模型可调 `set_plan(steps)`，运行时 `plan` 事件一到，面板就出现「打算这么做」编号清单；
  done/cancelled payload 也带 `plan_steps`，回放照样能看到。
- 指令层约束：多方向任务先 plan（3–5 条「动词+对象」）；ask_user 一轮最多 2 次，用户说「随便」就别问。

### 4.3 多轮与会话列表
- `store.recent_threads()` / `thread_runs()` + `GET /api/agent/threads`、`GET /api/agent/threads/{id}`。
- 面板头「最近的对话」：列出标题与轮数，点一下把历史问答铺回面板，并落进同一条 thread；
  当前 thread 存 `localStorage`，刷新页面不会断线；「开一段新的」清空并另起。

### 4.4 结果卡片可点、可收藏
- `MiniRow` 拆成「打开按钮 + 星标按钮」，星标走 `POST /api/agent/save`（`item_marks`，
  不经模型、失败回滚）。

**证据**（真模型，Chrome + playwright）：
- `帮我找点东西，平台我还没想好，你拿不准就先问我一句` → 11.3s 出提问卡（5 个方向选项）→
  点第一项 → Agent 继续 → 30s 内出 8 条结果 + 可点的建议；
- 紧接着发 `再来三条` → 落在同一条 thread，模型接着上一轮说「延续 AI 主题，这三条来自小红书…」；
- 「最近的对话」列出 6 条线程（标题 + N 轮），点开能回放两轮问答。

## 门禁
- `node scripts/check-ui.mjs` → 没有违规
- `uv run --with pytest python -m pytest tests -q` → 52 passed（新增 ask 单选直发、线程可续、
  answeredAsk 不回滚、星标收藏四条静态回归）
- `npm run build` → dist/assets/index-CDB0-w_k.js 463.96 kB

## 验证中发现并顺手修掉的两处
- 等用户回答时，轨迹底部还写着「下一步…」——下一步其实是用户。改成「等你选一下，或直接回一句」。
- set_plan 的触发门槛原来写的是「只做一件事就别调」，导致两三个动作的任务也不摊计划。改成
  「这轮要调两次以上工具就先 plan」。实测「找两条 B 站 AI 内容，各写一句总结」19.3s 出现四条计划
  （查分布 → 检索 → 挑两条 → 总结），64.7s 收尾。

## 顺手补的第三个问题：收藏了之后没地方看
Agent 能 `save_item`、结果卡有星标，但收藏完就消失了——没有任何界面能再找到它们。
补成信息流的一个筛选（不是另开一页）：
- `store.page(saved=True)` → `m.saved = 1`；`GET /api/feed?saved=1`；
- 顶栏「已收藏」按钮（`aria-pressed`）写进 URL `?saved=1`，刷新、返回都还在；
- 卡片头部对已收藏条目显示实心星；空态给的是「看全部内容」而不是「刷新」。
实测：`/?saved=1` → h1「我的收藏」1 张卡；关掉筛选回到「全部内容」30 张；`?q=zzzznotfound&saved=1`
显示「还没有收藏 / 跟底下的 AI 说「把这几条收藏起来」」。

## 这一轮没做 / 记为下一批
1. **计划出现得偏晚**：模型常先调 feed_stats 看规模，plan 落在第二个工具调用附近（约 19s）。
   可以再往前推——让 plan 成为「首个工具调用」的硬约束。
2. **线程内不显示「这轮用了哪条历史」**：回放只铺问答，没有轮次分隔与时间。
3. ~~收藏没有全局入口~~ → 本轮已补（见上）。
4. **ask_user 的选项没有「其他」兜底**：直接回一句支持，但输入框不明显（默认折叠在选项下面）。
5. **流式只在总结面板**：Agent 的 reply 仍是一次性 delta（模型本来只吐一段），没有打字机。
