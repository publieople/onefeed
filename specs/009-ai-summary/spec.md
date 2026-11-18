# 009 · 详情页默认 AI 总结（Agent 读一遍再说）

状态：方案待确认（2026-11-18）
关联：006-ai（模型顺序表）、005-detail（详情页与素材）

## 1. 要解决的问题

现在点开一张卡片，详情页先给「原文 / 播放器」。视频得自己看，长文得自己读——OneFeed 有模型、有插件、有全文，
却把「理解」这一步留给了用户。目标：**打开就是结论，原文随时可回到。**

用户原话（2026-11-18）：「详情页我觉得可以直接改成打开默认使用Agent总结, 想看的视频就让Agent去看一遍
然后以简洁的语言总结出来, 这样才能叫原生AI应用」。

## 2. 交互（前端）

详情页顶部两个分段：**AI 总结（默认）| 原文**。

打开页面时：

1. 立刻渲染已有的标题 / 作者 / 统计（feed 里就有，不等网络）。
2. 总结区先出骨架 + 一行状态「Agent 正在看…」，按阶段换文案：`取素材` → `读全文` → `写总结`。
3. 总结到达后渲染卡片：

   ```
   一句话结论（18–30 字，粗体）

   · [02:14] 要点一
   · [04:35] 要点二
   · 要点三（无时间戳时不带方括号）

   值得一看：[02:14]–[03:02] 为什么…… / [07:10] 演示了……

   注意：依据是标题、简介和热评，这条视频没有字幕，结论可能有偏差。
   ```

   底部一行小字：`依据 完整字幕 4.2k 字 · MiniMax-M3.1-Flash · 8.4s` + 「重算」「去原站」。

4. `[mm:ss]` 可点：B 站跳 `player.bilibili.com/player.html?bvid=…&t=<秒>`（iframe 内 seek，失败则打开
   `bilibili.com/video/<BV>?t=<秒>`）；其他平台点了直接滚到原文对应位置（能定位到段落就定位，不能就跳原帖）。
5. 「原文」页签：今天的详情页（播放器 / 正文 / 图片 / 评论）原样搬过去，一行不改。
6. 模型没配 key：不显示「AI 总结」页签，退回今天的行为；已在总结里有缓存时仍然展示（并标「缓存 · 未配置模型」）。

## 3. 素材怎么来（后端）

新增 `onefeed/summary.py`：

```python
def collect(store, host, item) -> dict:
    # 1) 已有的 detail（正文 / 媒体 / 统计），复用 details 表缓存，不重复抓
    # 2) 评论前 5 条（host.comments，失败就当没有）
    # 3) 插件声明的 summary 能力：host.summary_source(plugin_id, item) -> dict|None
    return {"title":…, "author":…, "duration":…, "stats":{…},
            "body": {"kind":"text|html","value":…}, "comments":[…],
            "source": {"transcript": str|None, "official": str|None,
                       "chapters": [...], "basis": "transcript|official|desc|comments"}}

def summarize(store, host, item_id, force=False, depth="normal") -> dict:
    # 缓存命中且未过期 -> 直接返回
    # ai.plan_chain(SUMMARY_PROMPT, payload) 失败 -> 规则摘要兜底
    ...
```

### 3.1 插件的 summary 能力（保持「宿主零平台代码」）

manifest 新增 feature `summary`，插件实现可选方法 `summarySource(ctx, {item}) -> dict`：

| 字段 | 含义 |
|---|---|
| `transcript` | 全文（字幕 / 转写 / 正文纯文本），超过 12000 字截断并标 `truncated: true` |
| `official` | 平台自带的总结（如 B 站官方 AI 总结），有则给 |
| `chapters` | `[{title, start}]`，用于把要点对齐到时间 |
| `basis` | `transcript / official / desc / comments`，决定前端「注意」那句怎么写 |

只在声明了 `summary` 的插件上调用；没声明的平台，宿主直接用 005-detail 的 body 当素材。

**B 站插件（0.5.0）**：一次 `ctx.cli.run(["bili","video","watch",bv,"--frames","0","--comments","5","--max-chars","12000"])`，
实测 **1.9s** 返回 `title/desc/owner/stat/duration/tags/chapters/ai_summary/transcript/hot_comments`。
- 有 `transcript.text` → `basis="transcript"`（带时间轴，要点可带 `[mm:ss]`）
- 只有 `ai_summary` → `basis="official"`
- 都没有 → `basis="desc"`，素材 = 标题 + 简介 + 热评 3 条 + 弹幕高频词（可选）
- 深度模式（用户点「更仔细地看」）：`bili video transcribe`（需 `bili asr setup`）或 `bili video frames`
  → 现阶段不做，留 TODO（模型是纯文本的，看不了图）

实测覆盖（2026-11-18，最近 5 条 B 站条目）：官方 AI 总结 1/5 命中；字幕 0/5（都是新闻短片）。
→ **「没有字幕」是常态**，降级链路必须体面，不能假装看过了。

**其他平台**：不新增方法——
- 知乎（回答/专栏）、掘金、V2EX：detail 的 html 正文直接进素材，质量最好。
- 小红书：正文常只有话题标签，靠图 → `basis="desc"`，注明「内容主要在图上」。
- 抖音：只有文案 + 5 条评论 → `basis="desc"`。

## 4. 模型侧

`SUMMARY_PROMPT`（`onefeed/summary.py`）：输出 JSON

```json
{"one_liner":"…","bullets":[{"text":"…","t":null}],"highlights":[{"t":134,"text":"…"}],
 "caveats":["…"],"confidence":"high|medium|low"}
```

规则：
- 只用素材里出现的信息，不补背景知识；素材没有数字就不写数字。
- `bullets` 3–6 条，每条 ≤ 60 字；有 `chapters` 时优先按章节组织并把 `t` 填成秒。
- `basis != transcript` 时 `confidence` 最高 medium，且必须写一条 `caveats`。
- 复用 006 的顺序表与 `_chat`：MiniMax 优先、失败自动切 DeepSeek；返回里带 `provider/model/ms`，
  详情页那行小字直接用它。
- 失败兜底：规则摘要（首段 120 字 + 统计 + 首条热评），`confidence:"low"`，标「未使用模型」。

超时 45s；模型调用与 `collect` 分开计时，便于在页面上说清慢在哪。

## 5. 存储与接口

`store.py`：`SCHEMA_VERSION = 4`，新表

```sql
CREATE TABLE IF NOT EXISTS summaries (
  item_id TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  provider TEXT, model TEXT, basis TEXT,
  created_at REAL NOT NULL
);
```

过期：默认 **不过期**（内容不会变），`refresh=1` 强制重算；素材里有 `expiresAt` 语义的平台（媒体直链）不影响总结。

API：
- `GET /api/item/{item_id}/summary` → `{supported, summary, from_cache, engine, ms}`
  - 插件未声明 `summary` 且没有 detail body → `supported:false, reason:"这个平台暂时总结不了。"`
  - 未配置模型且无缓存 → `supported:false, reason:"还没有配置模型。"`（前端隐藏页签）
- `?refresh=1` 重算；`?depth=deep` 预留给 ASR。

## 6. 落地任务

| # | 任务 | 文件 | 估时 |
|---|---|---|---|
| T50 | summaries 表 + get/save/drop | `onefeed/store.py` | 1.5h |
| T51 | manifest 加 `summary` feature；`host.summary_source()` | `plugin_runtime/{manifest,host}.py` | 1h |
| T52 | `onefeed/summary.py`：collect / prompt / summarize / 规则兜底 | 新文件 | 3h |
| T53 | `GET /api/item/{id}/summary`（缓存 + 错误口径） | `onefeed/api.py` | 1.5h |
| T54 | B 站插件 0.5.0：`summarySource` 走 watch | `onefeed-plugins/plugins/bilibili` | 2h |
| T55 | 前端：页签 + 总结卡 + `[mm:ss]` 跳转 + 阶段文案 | `web/src/pages/ItemPage.tsx`、新 `SummaryCard.tsx` | 4h |
| T56 | 测试：`test_summary.py`（collect 拼装、无字幕降级、缓存、无 key、provider 失败切换） | `onefeed/tests/` | 2h |
| T57 | 探针 `probes/check_summary_ui.py`：页签默认选中、骨架→卡片、`[mm:ss]` 可点、无 key 时隐藏 | `probes/` | 1.5h |
| T58 | 文档 + 截图（B 站有字幕 / 无字幕、知乎长文、暗色） | `specs/009`、`design/` | 1h |

合计约 **17.5h**，可分两刀：**第一刀 T50–T55（13h）** 就能上线默认 AI 总结；T56–T58 是门禁与文档。

## 7. 验收

- 打开 B 站视频详情页：≤ 12s 出总结卡；有字幕时要点带 `[mm:ss]` 且点击能跳。
- 打开知乎长文：≤ 10s 出总结，`basis=transcript`（用的是 detail 正文）。
- 打开没有字幕的抖音：总结卡出现，且「注意」明确写着依据是文案与评论。
- 没配 key：不出现 AI 总结页签，页面与今天一致。
- 同一 item 第二次打开：命中缓存，≤ 300ms。
- `uv run python tests/run_all.py --offline` 11 组全过；`node web/scripts/check-ui.mjs` 0 违规。

## 8. 风险与取舍

1. **素材不够就硬总结** → 用 `basis`/`confidence` 把「看了多少」写在脸上，宁短勿编。
2. **慢**：B 站素材 2s + 模型 6–10s；抖音/小红书要先开浏览器取详情（十几秒）→ 阶段文案顶住，
   且总结与详情并行请求、互不阻塞（详情缓存命中时总结走缓存正文，不再开浏览器）。
3. **成本**：每次总结约 3–6k 输入 token；缓存把重复打开降到零，重算要用户点。
4. **合规**：总结是派生内容，卡片底部永远保留「去原站」，导流不截流。

## 9. 交付状态（2026-11-18，B 站第一刀）

T50–T57 已落地，主仓 `5144634`、插件仓 `99aa323`：

| 项 | 实际做法 |
|---|---|
| 接口 | `GET /api/item/{id}/summary` 返回 `{ok, summary, from_cache, fetched_at}`，失败 `{ok:false, error}`；没有 `supported` 字段——总结永远尝试给出结果 |
| 无模型 | 不隐藏页签，退回「按素材顺序摘原句」，`engine:"rules"`，caveat 写明 |
| 插件素材 | manifest 加 `summary` feature；`host.summary_source()` 调插件的 `summarySource()`，插件没认领就直接返回 None，宿主拿详情缓存正文兜底 |
| B 站 | 插件 0.5.0：`bili video watch --frames 0 --comments 5`，一次拿字幕 + 平台 AI 总结 + 热评，约 2s |
| 前端 | 详情页两个页签（AI 总结默认 / 原文）；要点前的时间戳是按钮，点击切到「原文」并让播放器带 `t=秒&autoplay=1`；依据行写「依据 完整字幕 · 10697 字 · DeepSeek · deepseek-chat · 18.2s」 |
| 测试 | `tests/test_summary.py` 42 项（解析、素材、规则兜底、缓存、接口 404）；`test_store.py` 迁移断言升到 4 |

实测（`bilibili:video:BV1ZMWd6mE77`，字幕 6059 字）：**冷启动 18.3s**，返回 6 条带时间点的要点，点 `3:00` 后播放器从 03:02 开始播；第二次走 summaries 缓存。

### 踩坑：venv 里的 python 写不了 %APPDATA%

`bili video watch` 无条件调 `cards.mark_seen()` 写 `%APPDATA%\bili-cli\seen.json`。onefeed 的 venv python 在这个机器上对该目录没有写权限（`PermissionError: [Errno 13]`），子进程继承同一上下文，于是整个 watch 失败——`bili video info` 因为不写文件一直正常，容易误判成参数问题。

修法是 manifest 的两个新字段：

- `cli.env`：给 CLI 进程加环境变量，支持 `${state}`、`${plugin}`、`${appdata}`、`${localappdata}`、`${home}` 展开；
- `cli.seed`：把只读位置的文件复制进 `${state}` 下的私有目录（目标缺失或源更新时才复制）。

B 站插件把 `BILI_CLI_HOME` 指到 `${state}/toolhome/bili-cli`，并把 `credential.json` seed 过去，登录态仍然只在本机、插件读不到明文。

### 还没做

- 抖音 / 小红书 / 知乎的 `summarySource`（现在走详情正文兜底，等 detail 缓存才有素材）；
- `?depth=deep`（ASR）与 `chapters` 的实际消费（B 站 chapters 已透传，前端暂未渲染）；
- 时间戳跳转只认 B 站播放器，其它平台的 `t
eq` 还不统一。

