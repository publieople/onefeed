# 三档总结粒度 + 条目对话（2026-11-22）

给详情页加两件事：总结可以按「简洁 / 平衡 / 详细」重新生成并各自缓存；总结下面能就这一条内容追问，答复走真流式，图文条会带图。

## 一、三档粒度

档位定义在 `onefeed/summary.py:32-43` 的 `DEPTH_SPEC`，三档只改四件事：条数区间、每句字数、素材预算、覆盖要求。

| 档位 | id | 要点条数 | 一句话结论 | 单条字数 | max_tokens | 素材字符 | 带图 |
|---|---|---|---|---|---|---|---|
| 简洁 | `brief` | 2–3 | ≤24 字 | ≤28 字 | 1200 | 6000 | 2 张 |
| 平衡（默认） | `balanced` | 2–6 | ≤30 字 | ≤45 字 | 2200 | 14000 | 3 张 |
| 详细 | `detailed` | 6–10 | ≤60 字 | ≤80 字 | 3600 | 26000 | 3 张 |

配套：

- 不认识的档位一律回落 `balanced`（`depth_spec()`，`onefeed/summary.py:46-48`）：旧链接、手改 URL 不该让总结挂掉。
- 默认档位写在设置里（`summary_depth`），读不到/写坏了也回落 `balanced`（`configured_depth()`）。
- 缓存按 (item, depth) 分开存：`onefeed/store.py:106-113` 的 `summaries` 表主键改成 `(item_id, depth)`，`SCHEMA_VERSION` 提到 9（`onefeed/store.py:22`）。理由：同一篇的简洁稿和详细稿是两份东西，共用一行会在切档时看到上一档的正文。
- 「详细」档的 `_parse` 截断上限从 6 提到 10，否则模型写 9 条会被砍成 6 条。

## 二、两个流式端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/item/{id}/summary/stream?depth=brief\|balanced\|detailed` | meta 帧带 depth，正文逐行下发，收尾帧带 `summary.depth` |
| POST | `/api/item/{id}/chat/stream` | body `{"message": "...", "depth": "..."}`；thinking → delta… → done |

- 两个端点都是行协议（不是 JSON）：JSON 得等括号闭合才能解析，行协议每写完一行就能显示。
- 对话的上下文：`onefeed/summary.py:647-680` 的 `chat_messages()` 拼 system 规则 + 一条 assistant 开场「看完了，问我吧。」+ 最近 6 轮 history + 这一问；素材（标题、正文、评论摘要）和当前档位的总结都进对话，答不出就明说没讲。
- **图文条会带图**：`CHAT_IMAGES_MAX = 2`，取 `_source` 已抓到的前 2 张图拼进 user 消息的 content blocks，并在文字里写一句「附了这个条目的图，问图里的内容时直接看图回答」。之前不带给图时问「封面写了什么」只能答「素材里没有展示图片内容」。
- 出错口径：空 message → 400 `empty_message`；条目不存在 → 404；没配 key → 答复「还没配模型 key」。

## 三、前端

### 粒度切换（`web/src/pages/ItemPage.tsx`）

- tab 行右侧一组「总结粒度 简洁/平衡/详细」，`role="group" aria-label="总结粒度"`，每个 pill `aria-pressed`，选中态用 `layoutId="summary-depth-pill"` 滑动。
- 切档时**不塌面板**：旧正文保留并压暗（`opacity-55`），上方出现 `role="status"` 行「正在按「详细」重写… 9s」，秒数每 250ms 更新；完成后替换。测试里对应 `keepOld` 分支（`if (!keepOld) setSummary(null)`）。
- 命中缓存就秒切：`depthCache` 按档存，`from_cache: true` 时不显示进度条，正文立刻换。
- 初始档位跟设置里的 `summary_depth` 走，用户在本页点过就以本页选择为准（不同步回全局设置）。

### 条目对话（`web/src/components/ItemChat.tsx`，新文件）

- 位置：总结卡下面、评论上面，标题「问问这条 · 只谈当前这条，不带别的」。
- 发送后立刻两件事：user 气泡上屏、状态行 + 停止方块出现（思维链阶段写「正在想…」，开始出字后写「正在读这条…」），输入框 disabled 且 placeholder 换成「等它说完，或者按右边的停止」。
- 回复逐字追加（`/chat/stream` 的 delta），完事后输入框恢复，占位改回「就这条继续问…」。
- 停止：本地即时收尾 —— 落一条「停下了。」并打「按你点的停止收的尾」标记，不等后端 SSE 收尾（避免隐藏标签页里动画/流断掉后卡住）。
- 动效只用入场（`motion.li initial=...`），**不用 AnimatePresence / exit**：本机实测隐藏标签页里 rAF 被节流到 1fps，退出动画永远收不了尾，消息会卡在 DOM 里。
- 键盘：Enter 发送、Shift+Enter 换行、IME 组合期 `isComposing` 不发送；输入框 `rows` 自适应，`max-h-` 上限。
- 无障碍：消息区 `aria-live="polite"`。

### 设置页

「AI 助手」区多一张「默认总结粒度」卡片（`DEPTH_OPTIONS`，`web/src/pages/SettingsPage.tsx:124-128`）：三档 pill + 跟着选中项换的 hint + 右上「详情页里还能逐条临时改」。hint 与 spec 对齐：简洁「两三条要点」、平衡「2–6 条」、详细「6–10 条」。

## 四、验证

- `uv run --with pytest python -m pytest tests -q` → **142 passed**（新增 `tests/test_summary_depth.py` 9 个 test / 52 项 check，`tests/test_interaction.py` 新增 7 个 case）。
- `node scripts/check-ui.mjs` → 无违规；`npm run build` 通过（`index-CHTKxIDx.js` 453.77 kB、`ItemPage-*` 73.02 kB）。
- curl：`GET .../summary/stream?depth=brief` → meta `depth=brief` → status thinking → delta 分片 → done（1 条要点、MiniMax-M3.1-Flash、27762ms）。
- 真机（Chrome 1280×800，`--no-browser --port 8799`）：
  - V2EX 条目切「详细」：出现「正在按「详细」重写… 9s」+ 旧正文压暗，22s 后变 6 条要点（平衡稿是 5 条）；
  - 点回「平衡」：无进度条、正文立刻变回，命中缓存；
  - 问「这条里最关键的数字是什么？」→ 立即「正在读这条…」+ 停止键，约 9s 后答案引用「亏了三百多 / 79 元 / 169 元 / 279 元」；
  - 2s 后点停止 → 立刻落「停下了。」+「按你点的停止收的尾」；
  - 小红书图文条问「封面图上写了什么？照图上内容说」→ 答出主标题与英文手写句子，带图生效。

## 五、已知限制

- 首字仍受模型侧思维链影响：实测「详细」22–27s，「平衡」常在 5–9s；前端有秒数与骨架兜着，但慢是模型侧的。
- 粒度选择只在当前条目生效，不写回全局设置（设置页的「默认总结粒度」才是全局）。
- 窄屏没真机验证：只按 `flex-wrap` 推断 tab 行与对话卡在小屏会换行。
- 对话会带上当前档位的总结；若总结还在流式中，这一问只用素材，不带总结。
