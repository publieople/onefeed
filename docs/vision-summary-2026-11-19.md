# 让 AI 总结真正「看得见」：多模态读图方案（2026-11-19）

目标：解决「小红书图文总结几乎等于没总结」「B 站无字幕视频只能吃平台总结」。
本文先复盘业界做法，再给 onefeed 的落地方案与实测数据。

## 一、业界现在怎么做

### 1. 阅读器类（Folo / Readwise Reader）

- Folo 的「AI Summary」在服务端按条目正文生成，图片不参与摘要；图片进入 AI 的方式是**用户主动上传附件或在 AI 对话里引用**。
- 客户端会先把图片压缩再发：Folo 的 `processFile` 把图片缩到 **max 1920×1080、JPEG quality 0.85**，转 data URL 后随消息发送（`apps/desktop/layer/renderer/src/modules/ai-chat/utils/file-processing.ts`）。
- 结论：**摘要走文本、问答走图片**是成熟产品的默认分工——因为摘要要便宜、要快，而图片是重成本。我们要做的是把这条分工往前推一步：图片为主的内容，摘要也必须看图。

### 2. 图片为主的内容（小红书/Instagram 类）

- 它们的正文往往只有话题标签，信息全在图里。做这类内容摘要的工具普遍是「先取字、再描述」：OCR 抽文字 + 视觉模型生成画面描述，然后合并成素材。
- 多模态模型普及后，直接喂图比分两段更简单，且能保留版式信息（卡表、九宫格、对比图）。

### 3. 视频类（B 站/YouTube 的 AI 总结）

- 标准链路是 **ASR 字幕 + 关键帧抽样**：字幕给时间轴，关键帧给「画面在演示什么」，两条素材合并后再总结。封面一般只用来判断标题是否标题党。
- 我们现有的 `bilibili_extract` 就是这条链路；缺的是把它接进 onefeed 的总结素材里（现在 `--frames 0`）。

### 4. 接口层（这次核实的两家）

- **DeepSeek**：`deepseek-flash` 与现有 `deepseek-chat` 都接受 OpenAI 兼容的 `image_url` 内容块；`detail` 只认 `low / high / original / auto`（传 `default` 会 422）；单图最长边会被缩到约 1300×1300，**每图最多 1024 token**。
- **MiniMax**：`MiniMax-M3.1-Flash` / `MiniMax-M3` 原生多模态，图片 `image_url`、视频 `video_url`；`detail` 认 `low / default / high`（low ≈ 几百 token，default ≈ 1k–3k）；单图 ≤10MB，请求体 ≤64MB；`reasoning_effort` 可调低档。

## 二、本机实测（2026-11-19，真实库、真实图片）

素材：3 张 B 站封面（296KB / 303KB / 166KB）+ 1 张小蓝图，prompt 为「用中文总结这几张图」。

| 配置 | 图片数 | prompt tokens | 输出 tokens | 耗时 | 结果 |
|---|---|---|---|---|---|
| `deepseek-chat` detail=low | 3 | **613** | 268 | **2.3s** | 完整读出图内中文（「屎山论剑」「世子之争」等），三条要点准确 |
| `deepseek-flash` detail=low, max_tokens=4000 | 3 | 639 | 1353（其中 1115 思考） | 7.9s | 同样准确，但思考 token 是正文的 4 倍 |
| `MiniMax-M3.1-Flash` detail=low + reasoning_effort=low | 4 | 1911 | 290（151 思考） | 5.1s | 行协议（TLDR + 要点）完全守规矩，读出九宫格阵营分类 |
| `deepseek-chat` 单图 | 1 | 232 | 307 | 2.4s | 描述细到角色台词 |

两个重要坑（已复现）：

1. **推理型模型会把输出预算吃光**：`deepseek-flash` 与 MiniMax 默认思考，`max_tokens=500` 时 `finish_reason=length`、正文为空。要么把 `max_tokens` 提到 2500–4000，要么 `reasoning_effort=low`。
2. **签名图片会过期**：小红书图片直链带时效签名，隔天再取返回 0 字节，模型侧直接 400/422。取图必须走宿主 `/api/media` 边车并在成功后缓存字节，不能把 CDN 直链丢给模型。

## 三、方案：图文混合，一次调用

### 3.1 素材选择（宁少勿多）

| 内容类型 | 取几张 | 取哪几张 | 理由 |
|---|---|---|---|
| 图文（images） | 3 | 第 1、2、3 张 | 小红书一篇通常 3–9 图，前 3 张覆盖封面与主体；后面多是细节 |
| 视频（video） | 3 | 封面 + 2 张关键帧 | 封面给主题，帧给「在演示什么」；B 站 `--frames 2` 现成 |
| 文章/动态 | 0 | — | 正文足够，图片多为配图 |

### 3.2 图片预处理

- 统一经 `/api/media/{item}/{slot}` 代取（已处理 Referer / cookie / 限流）。
- 转 JPEG、长边 ≤1024、quality 0.82，base64 后发；单张约 60–150KB。
- 缓存：按 `item_id + slot` 存字节与哈希，签名过期自动重取一次；失败就跳过这张，不让整条总结失败。
- `detail`：默认 `low`；图表/截图类内容（小红书卡片、数据图）用 `high`，靠内容类型 + 平台启发式判断。

### 3.3 调用与降级

- provider 配置增加 `vision: true|false`（DeepSeek / MiniMax 两家默认 true）。
- 主路径：文本素材 + 图片块同一条 user 消息 → 现有行协议不变，前端流式打字机不用改。
- 降级链：vision provider 失败 → 同 provider 纯文本（现有行为）→ 规则摘句。
- `basis` 增加 `visual` 档，前端「依据」显示「3 张图 + 简介」，让用户知道结论看过图。

### 3.4 代码落点

1. `onefeed/summary.py`
   - `_source()`：读 `payload["images"]`、`item.cover`、插件返回的 `images`，产出 `images: [{slot, kind}]`。
   - `_material()`：文本部分不变；新增 `_visual_material()` 返回图片块。
   - `build()` / `stream_build()`：把图片块拼进 messages；`ai.complete/stream_complete` 支持 content 数组。
2. `onefeed/ai.py`
   - `_post` / `_stream_post` 接受 `list[dict]` 形式的 content（现在只接受 str）。
   - 新增 `_image_block(url_or_b64, detail)` 与 `VISION_HINT`。
3. `onefeed/media.py`
   - `resolve_slot` 增加 `poster`/`img-N` 的缓存与过期重取；新增 `read_image_bytes(item_id, slot)` 供总结使用。
4. 插件（onefeed-plugins）
   - `xiaohongshu` 增 `summarySource`：返回 `images`、`title`、`desc`、`basis:"images"`。
   - `bilibili` 的 `buildSummarySource` 打开 `--frames 2`，并返回 `cover`。
5. 前端
   - `ItemPage` 的 `SummaryPanel`：`basis === "visual"` 时显示「依据：N 张图」。
   - 可选：gallery 上标出「AI 已读这张」。

### 3.5 成本与延迟预算

- 3 图 + 600 字文本：DeepSeek ≈ 800–1000 prompt tokens、2–3 秒；MiniMax ≈ 2000 tokens、5 秒。
- 按每天 100 条图文总结估算：DeepSeek 约 10 万 prompt tokens/天，成本可忽略。
- 结论：**不需要先做 caption 缓存**；直接多模态更简单、信息更全。caption 只在「provider 不支持视觉」时才作为降级。

## 四、实施顺序（建议）

1. `ai.py` content 数组支持 + `summary.py` 拼图（半天）→ 用现有小红书条目验证。
2. 插件补 `xiaohongshu.summarySource` 与 `bilibili` 关键帧（半天）。
3. 前端 `basis=visual` 文案与「已读图」标记（半天）。
4. 图片缓存与过期重取（半天）。

## 五、风险与对策

| 风险 | 对策 |
|---|---|
| 推理型模型吃光 token | 统一 `max_tokens ≥ 2500`；MiniMax 用 `reasoning_effort=low` |
| 图片签名过期 | 走边车取图 + 字节缓存 + 失败跳过 |
| 视觉模型不可用 | 回退纯文本总结，`basis` 不变 |
| 版权/隐私 | 图片只在本机与模型之间传输，不上传第三方存储；用户可在设置里关「读图总结」（设置 → AI 助手 → 总结时读图，`vision_summary`） |

## 六、落地实现（2026-11-19 晚）

已按上面方案实现并真机验证：

**取图链路**

- `onefeed/media.py`：`fetch_image(url, referer, plugin_id, cache_key)` 走宿主边车取流，字节缓存在 `state_root()/image-cache`（sha1 文件名，TTL 6 小时，单张上限 8MB，失败重试一次）；`read_slot_image(item_id, slot, detail, plugin_id)` 复用已有的 `resolve_slot`，支持 `img-N` 与 `poster`。
- `onefeed/summary.py`：`_collect_images` 先取 `payload.images` 前三张，一张都取不到时用 `row.cover` / `media.poster` 兜底；**签名过期**（小红书 xhscdn 直链带时间戳）时调 `_refresh_detail` 让插件重取一次详情再试。
- 图片与正文一起按 OpenAI 兼容的 `image_url` 内容块发给模型，`detail="low"`、`base64` data URL；带图被端点拒绝（400/422）自动退回纯文本，`images` 记 0。

**思考预算**

- `MAX_SUMMARY_TOKENS` 1100 → 2200：推理型模型的思考也算输出，1100 会被截成空正文。
- `ai.py` 新增 `_reasoning_hint`：MiniMax 官方域名自动带 `reasoning_effort="low"`（显式配置优先，其他网关不加这个字段以免 400）。实测同一张 3 图消息：不加参数 27.8 秒 / 869 段思考 / 正文 219 字，`low` 后 4.1 秒 / 60 段思考 / 正文 143 字。
- 流式再补一层阶梯：有图时依次试 `(图, 2200)` → `(图, 4400)` → `(纯文本, 2200)`，最后一档仍空才走规则兜底。

**可见性**

- 总结 payload 新增 `images` 字段，详情页依据行显示「依据 标题与简介 · 458 字 · 3 张图」。
- `basis` 新增 `visual`（正文不足 60 字且用了图时），前端文案「图片」。

**验证数据**

- `xiaohongshu:note:6afd0c47000000002602670a`（3 张 webp）：流式 5.5 秒，`images=3`、`engine=llm`、MiniMax-M3.1-Flash，要点里出现只有图中才有的对比数字与报价。
- B 站无字幕视频走封面（poster 槽，jpeg 约 200KB）同样能取到。
- `tests/test_summary.py` 新增三条用例：图片拼块、端点拒图回退、关掉读图不取图；全量 pytest 97 passed。

**开关**

- 设置 → AI 助手 → 「总结时读图」（`vision_summary`，默认开）。关掉后 `_source` 不取图、消息纯文本、`images=0`。
