# 交付记录：Agent 三形态 + 性能四批次（2026-11-19）

对应两份设计文档：`docs/agent-interaction-redesign-2026-11-19.md`（Agent 交互）与
`docs/perf-audit-2026-11-19.md`（性能）。这里只记「做了什么、怎么验的、还差什么」。

## 1. Agent 从「一个输入框」变成「三种形态共用一个会话」

改造前的问题：AiDock 只挂在信息流页，会话状态活在组件里。Agent 一旦用 ui_open_item 打开详情页，
整个对话框随 FeedPage 一起卸载 —— 用户看着它干活，干到一半它自己消失了。

现在：

| 形态 | 什么时候 | 长什么样 | 代码 |
| --- | --- | --- | --- |
| 唤起器 | 默认收起 | 信息流底部胶囊；详情页右下圆钮 | `agent/AgentSurface.tsx` 的 `AgentLauncher` |
| 底部抽屉 | 信息流 / 窄屏（<1080） | 42–62vh 抽屉，焦点陷阱，Esc 收起 | `agent/AgentSurface.tsx` 的 `AgentSheet` |
| 右栏 | 详情页且宽屏 | 380px 常驻 aside，详情正文自动让位 | `agent/AgentRail.tsx` |
| 整页 | `/agent`、`/agent/:threadId` | 左历史 + 右对话 | `pages/AgentPage.tsx` |

关键点：

- **会话不随路由重建**：`AgentProvider` 挂在 `App` 里、`Routes` 之上，`turns/busy/live/threadId` 都存在 Provider。
  Agent 自己导航到详情页时，形态从 sheet 切成 rail，对话内容原样还在
  （实测：Agent 打开 `/item/bilibili:video:BV1DwsK6aE5R` 后 rail 里仍有 2 个 turn）。
- **上下文注入**：详情页 `setFocus({id,title,platform})`，`ask()` 带上 `context`，后端 `_focus_hint()` 拼进 prompt
  —— 用户说「这条」「总结一下」不必再问是哪条。
- **持久化三层**：L1 `localStorage onefeed.agent.thread`（会话指针）→ L2 `agent_threads/agent_runs`（线程内容）
  → L3 SSE `last-event-id` 续传（`sse_stream` 已支持）。刷新或隔天进来，`/agent` 会按指针把这段铺回来
  （实测 1 轮对话恢复成 2 条消息）。
- **历史**：`AgentHistory` 列表（标题 + N 轮），`/agent` 左栏 20 条真实线程，可点回放。
- **键盘**：`/` 与 `⌘/Ctrl+K` 唤起并聚焦输入框（命中后先 `preventDefault`，否则地址栏会把焦点抢走）；
  `Esc` 只收起不打断；`⌘⇧H` 历史；sheet 内 Tab 环绕；rail 不做焦点陷阱（它不遮内容）。
- **形态切换动效**：只做「收敛 / 展开」一档（`layoutId` + `SPRING_SOFT`），不给每一次跳转都配飞行。

## 2. 性能：从「能跑」到「滚动不掉帧」

### 改了什么

| 项 | 位置 | 做法 |
| --- | --- | --- |
| PF-1 顶栏背景模糊 | `web/src/components/TopBar.tsx` | 去掉 `backdrop-blur`，改不透明 `bg-paper` |
| PF-2 巨型合成层 | `web/src/theme.css` 的 `.page-shell` | 删掉常挂的 `will-change`（那张容器实测 4324px 高） |
| PF-3 轮询重渲染 | `web/src/App.tsx` | `sameRun()` 先比再 set，`setProgress` 改函数式短路 |
| PF-3 顶栏重复绑监听 | `web/src/components/TopBar.tsx` | 主题快捷键 effect 补依赖，不再每帧解绑重绑 |
| 卡片重渲染 | `web/src/components/Card.tsx` | `memo(Card)`；FeedPage 的 `openItem` 改 `useCallback` 保引用 |
| 30 套布局动画 | `web/src/pages/FeedPage.tsx` | 超过 12 张连 `motion.div` 都不建，直接普通 div |
| 媒体不缓存 | `onefeed/api.py` | `cache-control: public, max-age=600, stale-while-revalidate=60` + ETag 命中回 304 |
| 详情页冷启动 | `web/src/api.ts` | `detailCache` 60s，返回列表再点回来不再等 7.9s |
| 图片排在视频后面 | `onefeed/media.py` | `IMAGE_SEMAPHORE(8)` 与视频 `SEMAPHORE(4)` 分队列 |
| 单包 475 kB | `web/src/App.tsx` | Settings / Market / AgentPage / NotFound 改 `lazy` + Suspense |
| 缓存表只进不出 | `web/src/api.ts` | prefetch 24 条带 TTL 清理、feedCache 20、detailCache 12 |

详情页刻意**不拆包**：共享元素转场要在点击后立刻拿到新快照，异步 chunk 会在转场里插一段空白。

### 实测对比（Chrome 1280×860，本地 8799，924 条数据）

| 指标 | 改前 | 改后 |
| --- | --- | --- |
| 平滑滚动三屏 max frame | 173.4 ms | **14 ms** |
| 滚动超过 33ms 的帧 | 6 帧 | **0 帧** |
| 滚动平均帧 | 17.11 ms | **13.34 ms** |
| 换筛选（V2EX）LayoutDuration | 57 ms（旧样式 A/B） | **13 ms** |
| 媒体二次请求 | 200 + 98 798 B | **304 + 0 B** |
| 主包 JS | 475.11 kB | **435.43 kB**（gzip 143.43） |
| 按需 chunk | — | Settings 30.61 / Market 7.52 / AgentPage 3.49 / NotFound 0.80 kB |

换筛选的 TaskDuration 仍在 250–290ms（30 张卡渲染 + 图片解码）；同会话 A/B 对比旧样式是 280–296ms，
属于噪声内 —— 这一项不是本次目标，真要再压得动「骨架先上、图后到」。

### 门禁

- `tests/test_perf.py`（新增 10 条）：顶栏无模糊、effect 有依赖、page-shell 无 will-change、
  轮询短路、Card memo、懒加载分包、四张缓存表有上限、detail 缓存、媒体可缓存 + 304、图片独立队列。
- `uv run --with pytest python -m pytest tests -q` → **64 passed**。
- `node scripts/check-ui.mjs` → 没有违规。
- `npm run build` → `dist/assets/index-LY3vFXHN.js` 435.43 kB。
- 真机（playwright + Chrome）：唤起器 → sheet → Agent 自己打开详情页 → **rail 接管且会话不丢** →
  收起 → 重新唤起 → 2 turn 仍在；`/agent` 左栏 20 条线程、带 threadId 刷新可恢复对话；
  `/settings`、`/market`、`/agent` 懒加载无 console 报错。

## 3. 还没做

- 窄屏真机（小于 1080 的 rail→sheet 切换只按代码推断，未在手机上验）。
- 封面 / 头像原始尺寸过大（1890px 显示 338px、评论区头像 2048px）：需要图片代理 + 缩放，
  牵涉第三方域名白名单，单独排期。
- SSE 断线续传前端只记了 threadId，`last-event-id` 自动重连还没接。
- 线程重命名 / 删除 / 分叉 / 导出 md（设计文档 P1/P2）。
