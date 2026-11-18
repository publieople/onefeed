# 010 · AI 原生化：让模型自己搜、自己挑

状态：已落地（2026-11-18）
关联：006-ai（模型顺序表）、009-ai-summary（详情页总结）

## 1. 要解决的问题

006 的 AI 助手是「一次出计划 + 按关键词 LIKE 盲搜」：

- 模型只看到用户那句话，写出 `{platforms, keyword, since, sort}` 就结束了；`store.page()` 拿
  `LIKE %keyword%` 单子串去撞，撞到什么给什么。模型没有机会**看结果、换词、补条件、放弃**。
- 词边界问题：在 127 条 B 站真实数据里 `LIKE %AI%` 命中 31 条，按词边界只有 24 条——
  7 条假命中（said / main / rail 里的 ai），占 23%。
- 时长、点赞、条数这类指令进了 prompt 但没有执行通道，只能被静默丢弃。

评测口径（12 条查询，人工标注应命中）：precision@10 = 0.67，其中 4/12 条查询有假命中。

## 2. 方案

用 **Pydantic AI 2.70**（`pydantic-ai-slim[openai]`）把「检索」从一次函数调用改成一段可回头的对话：

```
用户一句话
   ↓
Agent（instructions：先搜 1-3 个词；最多 6 次工具；只从候选挑；不许凑数）
   ├── search(terms, platforms, kinds, since, sort, limit, duration_min, duration_max, like_min)
   ├── get_item(id)      # 看某条全文再说
   └── similar(id)       # 同题其它平台
   ↓
Answer{reply, picks:[{id, why}]}
   ↓
宿主按 id 回填本地行 → plan/reply/items/count/suggestions/understood（响应结构与 006 完全一致）
```

选它而不是 LangGraph / OpenAI Agents SDK 的理由见 006 plan；生产约束：
`import pydantic_ai` 要 1.7s，所以**只在真正要用时 import**，关掉开关时连模块都不加载。

## 3. 检索层（P0，与框架无关）

`store.search_items()`（新增，`page()` 一行未动，前端筛选仍走旧路径）：

- 候选池 `max(60, limit*5)`，先按平台 / kind / since / 时长 / 点赞 / exclude 在 SQL 里硬过滤；
- 打分：英文词用词边界 `(?<![0-9a-z])term(?![0-9a-z])`、中文用子串；
  **标题 ×3 / 正文 ×1 / 作者 ×0.2**，同词同字段只记一次；
- 有词就按分降序稳定排序并丢掉 0 分；没词返回候选池（browse 用）；limit 上限 60。

`store.cluster_items()`：同 `cluster_id` 的其它平台条目，按热度排，给 `similar` 用。

工具参数在进 SQL 之前先归一化（真模型实测踩出来的）：

- 平台别名 → id：`B站 / b站 / 哔哩哔哩 → bilibili`，其余同理；不归一化时「B站」直接搜出 0 条，
  模型会以为库里没有，反复改词。
- 时长参数名带单位：`duration_min_sec / duration_max_sec`。原名 `duration_max` 时模型把「十分钟」
  传成 10（秒），过滤后 0 条。
- `sort` 别名：`likes / hot / popular / 最热 → engagement`，`latest / new → freshness`。
- 同条件重复搜命中本次会话缓存，不再走 SQL；工具次数用满后返回一句明确的错误而不是空数组。

## 4. 开关与降级

| 开关 | 位置 | 默认 | 作用 |
|---|---|---|---|
| `ai_agent` | 设置 | `true` | 关掉立刻回到 006 旧路径 |
| `ai_agent_max_tools` | 设置 | `6` | 每次最多几次工具调用（1–12） |
| `ONEFEED_AI_AGENT` | 环境变量 | — | `0/false/off/no` 压过设置 |

降级链：agent 抛异常 / 超时（45s）/ 没装包 / 没配 provider → 记一条 `_LAST`（error 前缀 `agent: `）
→ 走 `_chat_legacy()`，用户看到的响应结构不变，只是 `engine` 从 `agent` 变回 `llm/rules`。

## 5. 验收标准

- **AC-1** `ai_agent=False` 或 `ONEFEED_AI_AGENT=0` 时 `sys.modules` 里没有 `pydantic_ai`，chat 仍返回完整结果。
- **AC-2** 「AI」这种两字母词不再命中 said / main / rail；多词按 OR；标题命中排在正文命中前。
- **AC-3** 时长上下限、点赞下限、排除集在 SQL 层生效；没有内容时返回空数组而不是凑数。
- **AC-4** agent 一次工具调用即可完成；模型编造的 id 不出现在 `items` 里；挑 0 条时 reply 是正常人话。
- **AC-5** 超过 45s 直接抛 TimeoutError 并降级，不无限等。
- **AC-6** `GET /api/ai/status` 带 `agent: true/false`；`POST /api/ai/chat` 的 `engine` 如实标 `agent`。
- **AC-7** `uv run python tests/run_all.py --offline` 全过；新增 `test_agent.py` 35 项。
- **AC-8** 模型写「B站」也能搜到；`duration_max_sec=600` 卡住的是 10 分钟而不是 600 秒。

实测（2026-11-18）：`test_agent.py` 35 项全过；`run_all --offline` 16 组全过。

真模型端到端（本地 749 条库，问「找几条 B 站讲 AI 的视频，十分钟以内」）：

| 轮次 | 结果 |
|---|---|
| 修复前 | 落回旧路径（llm）：脚本把「十分钟」当 10 秒 + 「B站」别名 → 连续 0 结果 → MiniMax 打了 9 次工具 → 撞 `tool_calls_limit` 整轮失败 |
| 修复后 | `engine=agent`，3–4 次工具，16–19s，8 条候选全部 `duration ≤ 600`，首条为「【Re:从零开始的AI学习】你不知道的大模型真实价格」 |

FunctionModel 离线 68ms；TestModel 冒烟 39ms。precision 复测待接 12 条标注集（人工抽查 8 条全部相关）。

## 6. 落地清单

| # | 任务 | 文件 | 状态 |
|---|---|---|---|
| T49a | `search_items` / `cluster_items` + 词边界打分 | `onefeed/store.py` | ✅ |
| T49b | 开关字段与校验 | `onefeed/settings.py` | ✅ |
| T49c | `agent.py`：Agent / 三工具 / Answer / 超时 / plan 映射 | `onefeed/agent.py` | ✅ |
| T49d | `chat()` 分流 + `_chat_legacy` + status.agent | `onefeed/ai.py` | ✅ |
| T49e | 验收脚本（35 项，含别名/秒/排序归一化） | `tests/test_agent.py` | ✅ |
| T49f | 全量接入 + test_ai 关 agent 前置 | `tests/run_all.py`、`tests/test_ai.py` | ✅ |

## 7. 风险与取舍

1. **多一跳延迟**：agent 至少一次模型 + 一次工具往返；比旧路径多 1–3s。可接受——旧路径快但错。
2. **依赖体积**：+约 40MB（openai、pydantic-graph、tiktoken 等）。桌面端可接受。
3. **模型不听话**：instructions 与 `UsageLimits` 双保险（request_limit = max_tools+3，tool_calls_limit = max_tools+1），
   超限抛错即降级，不会无限循环。
4. **keyword 语义变窄**：前端「用这个条件刷」仍走旧 LIKE，所以 plan.keyword 只放**一个最有代表性的词**
   （而不是 OR 串），避免点一下变成零结果。
