# 006 · AI 助手：把一句话变成一次检索

状态：P0 已实现（2026-11-17）。后端 `onefeed/ai.py`，接口 `POST /api/ai/chat`，前端 `web/src/components/AiDock.tsx`。

## 1. 这个功能解决什么

原来的筛选框是给人填条件的：输入「今天 B 站的 AI」，用户得自己知道「今天」对应 since、「B 站」是平台、「AI」是关键词。
现在把它换成一句人话，让宿主去拆条件——拆完照旧查本地 SQLite，结果卡片不变、详情页不变、原帖入口不变。

它是入口的替换，不是搜索的全新实现：能找什么，取决于库里已经采到什么。

## 2. 分工：模型只做理解，不碰内容

| 环节 | 谁做 | 说明 |
|---|---|---|
| 听懂话（平台 / 类型 / 时间 / 关键词 / 排序 / 意图） | 模型或规则 | 输出固定 JSON，字段进白名单 |
| 查内容 | 宿主（SQLite） | 模型拿不到、也编不出条目 |
| 措辞（那句「挑了 N 条」） | 模型或规则模板 | 说错也只影响一句文案 |
| 渲染 | 前端 | 卡片、详情页、原帖跳转都是既有组件 |

这条线决定了三件事：断网可用（规则引擎同等功能）、不会幻觉出不存在的内容（条目都带 id）、
「它凭什么推荐这条」永远解释得清（平台 / 关键词 / 时间 / 排序都在 plan 里）。

## 3. 两个引擎与降级

```
POST /api/ai/chat
  ├─ settings.ai_api_key（或 ONEFEED_AI_KEY）为空 → 规则引擎（smart.parse_query + 本地排序）
  └─ 有 key → 调 {ai_base_url}/chat/completions，要求 response_format=json_object
        ├─ 解析成功 → 采纳（字段再过一遍白名单）
        └─ 超时 / 非 JSON / 网络错 → 静默落回规则引擎
```

降级是设计目标，不是兜底：演示现场不赌 WiFi，赛前不配 key 也必须能跑完整动线。

## 4. 检索计划（plan）

```json
{"mode":"find|browse","platforms":[],"kinds":[],"since":"today|week|null",
 "keyword":"","sort":"freshness|engagement","reply":"一句中文"}
```

- `platforms`：`bilibili / xiaohongshu / douyin / juejin / v2ex / zhihu / zhihu-hot`，空数组 = 全平台。
- `kinds`：`video / images / article / short / list`，空数组 = 不限。
- `since`：`today` → 本地当天起点（按 UTC 日界再回拨 8 小时），`week` → 最近 6 天。
- `mode=`browse`：不按条件筛，按平台轮着抽，一屏不全是一个来源；「换一批」靠 exclude 上一批 id。
- `reply`：≤60 字，只有模型能给；规则引擎用模板拼。

## 5. 规则引擎怎么拆一句话（没 key 时的真实口径）

1. `smart.parse_query` 先做平台别名、kind 词、时间词、「含 X」。
2. 关键词再洗两遍：
   - 语气词（随便 / 来点 / 换一批 / 无聊 / 刷刷 / 看看）与疑问词（有什么 / 有没有 / 哪些 / 什么）删掉；
   - 功能词按**子串**删（`把最近`、`出来`、`内容`……），再按整词过滤（`_STOP_TOKENS`）。
   不洗的话每句话都会带一个假主题（「把最近」「聊」），结果必然 0 条。
3. 追问继承：消息只剩修饰词（`换成最热的` / `只要今天的` / `再看看`）时，平台、关键词、时间沿用上一轮 plan，
   只覆盖排序或时间。plan 由前端挂在 assistant 历史轮次上传回，后端从 `history[].plan` 取。
4. 平台与关键词都为空且不是追问 → 视为全库浏览，不硬凑关键词。

## 6. 交互（AiDock）

- 位置：底部固定胶囊，页面滚动不跟随；手机上不挡卡片顶部。
- 收起态：输入框 + 「刷一刷」；回车即问，历史轮次最多回传 4 轮。
- 展开态：向上弹出面板（max-h 62vh），顺序是「你说的话 → 我理解的（chips）→ 结果条数 + 引擎标记 → 最多 8 条迷你结果」。
- 三个动作：「用这个条件刷」（把 plan 派发给信息流页做筛选，关面板）、「换一批」（exclude 本批）、点条目进详情页。
- 建议词按 plan 生成：多平台给「只看 X」，freshness 给「换成最热的」，没有时间给「只要今天的」，没关键词给「找点 AI 的」。
- 「手动筛选」折叠着原 FilterBox，谁想填条件仍然能填。

## 7. 设置与凭据

- 字段：`ai_base_url`（默认 `https://api.deepseek.com/v1`）、`ai_model`（默认 `deepseek-chat`）、`ai_api_key`。
- key 存 `settings.json`，进程内只在发请求时读；`GET/PUT /api/settings` 一律返回空串（`SECRET_KEYS` 掩码），
  插件永远看不到；设置页留空表示「不改」，单独一个「清除 key」按钮才清。
- 环境变量 `ONEFEED_AI_KEY` 可覆盖文件里的 key（演示机可临时注入，不落盘）。

## 8. 验收（test_ai.py，40 项）

- 没 key → engine=rules；「只看今天 B 站的 AI 视频」→ 平台/B 站、类型视频、关键词 AI、结果全部同源同类型。
- 「知乎」→ zhihu（推荐流），「知乎热榜」→ zhihu-hot，长别名先剥。
- 「无聊，随便来点」→ browse，结果跨 ≥2 平台；exclude 不重复上一批。
- 追问「换成最热的」（带上一轮 plan）→ 平台与关键词不变、排序变 engagement、结果非空。
- PUT key 后：回包与 GET 都不含明文，磁盘上确实有，engine 变 llm。
- 模型返回非 JSON / 抛超时 → 落回规则且解析仍正确。
- 空消息 → 400 `empty_message`，不瞎猜。

## 9. 已知边界

- 规则引擎只认词，不懂语义（「最近在纠结要不要换手机」会被当成关键词）。有 key 时才真"理解"。
- 结果受库内数据限制：没采到的平台/时间窗，问也问不出来；搜索匹配的是标题与摘要，不搜全文。
- 不做生成式摘要与多轮追问式推荐（"还有吗" 只能靠换一批），避免模型替平台内容下结论。
- 同平台同标题在结果层去重（热榜会把同一问题按不同 id 收两次）。

## 10. 多模型顺序表（2026-11-17 追加）

原来只有一组 `ai_base_url / ai_model / ai_api_key`。实际用起来是两个供应商轮流上班：
MiniMax 的 token plan 便宜、DeepSeek 稳，谁挂了都不能让 AI 入口整块退回规则解析。

- 设置字段 `ai_providers`：数组，最多 5 条，每条 `{id, name, base_url, model, key, enabled}`；
  顺序即优先级。启用且填了 key 的才上场，全部不可用时才落回 `ai_api_key` 单模型字段（兼容旧配置）。
- `_provider_list()` 的优先级：环境变量 `ONEFEED_AI_KEY`（临时覆盖，不落盘）→ `ai_providers` 顺序链 → 旧单模型字段。
- `plan()` 遍历整条链：任一模型返回可解析的 JSON plan 就用它，并在 plan 上记 `provider`；
  抛 `URLError / TimeoutError / OSError / ValueError / KeyError / RuntimeError` 一律记进 `_LAST` 后换下一个。
  全挂 → 规则解析，`provider` 为空串。
- `GET /api/ai/status` 多返回三样：`active`（当前会用的模型名）、`providers`（脱敏链，带 `key_set` / 末四位）、
  `last`（上一次尝试：`{at, provider, ok, error, tried}`）。
- 新增 `POST /api/ai/test`：传 `{id}` 测已存的，或传 `{base_url, model, key}` 测草稿；key 留空时按 id 继承已存的。
  返回 `{ok, ms, provider, model, reply}` 或 `{ok:false, error}`。
- 凭据口径不变：`GET /api/settings` 里每条 provider 的 `key` 一律空串，只回 `key_set` 与 `key_hint`（末四位）；
  `PUT` 时空 key 表示「不改」，按 id 继承旧值。「清除所有 key」是单独一个动作（把 `ai_providers` 清空）。

实测（2026-11-17）：MiniMax `MiniMax-M3.1-Flash` 982 ms、DeepSeek `deepseek-chat` 351 ms；
把 MiniMax 的模型名改成一个不存在的，`/api/ai/chat` 仍返回 `provider=DeepSeek`，`last.tried=["MiniMax","DeepSeek"]`。

## 11. 设置页与动效（2026-11-17 追加）

设置页原来把所有 section 平铺，一屏放不下，改完还得滚回顶部按保存。

- 两栏：左侧 184px 分类导航（跟着滚动高亮），右侧分组卡片。小于 `lg` 时导航隐藏，只留卡片。
- 每个分组默认收起，收起态露一行摘要（如「12 条/平台 · 保留 14 天 · 不自动更新」），
  只有「运行状态」和「AI 助手」默认展开。展开/收起用 `AnimatePresence` 做高度 + 透明度过渡。
- 有未保存改动时，底部浮出一条胶囊「有未保存的改动 · 保存 / 放弃」，不占文档流、不推动页面；
  保存或放弃后浮条淡出。之前那版把它做成 sticky 顶栏，第一次输入会把整页往下顶一下，已否掉。
- 动效统一用 `framer-motion`（已在依赖里但此前零使用）+ 少量 CSS：`rise` 列表进场、`fade-in`、
  `button:active` 轻微缩放、分段控件用 `layoutId` 滑块、路由切换只做透明度过渡、toast 从底部弹入。
- **坑**：路由外层容器不能带 `transform` / `will-change: transform`，否则后代的 `position: fixed`
  （底部 AI 胶囊、toast）会以整页为参照，跑到页面最底部看不见。`.page-shell` 只留 `will-change: opacity`。
