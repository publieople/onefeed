# 关注流：平台原生关注，不做自建关注列表

2026-11-24。入口在顶栏「信息流 / 关注」；关注页默认列表，另有时间线、紧凑两种布局。
这一版只做平台自己的关注流，OneFeed 自建关注作者列表留到后续。

## 为什么不是复制信息流

关注流做成了插件的第二条 feed，而不是第二个「信息流」：

- 数据还是同一张 `items` 表，一条内容可以同时在信息流和关注流里出现，但不会存两份；
- 用 `item_feeds` 记录「这条内容属于哪条流、第一次/最后一次在流里见到」；
- 主信息流的刷新演出、平台冷却、顶栏进度胶囊完全不知道关注流存在，关注同步不会把首页内容重排。

这样详情页、评论、AI 总结、收藏、已读都直接复用现有能力，关注页只是换了一种取数方式和排版。

## 数据模型（schema v10）

`onefeed/store.py` 新增：

```sql
item_feeds(item_id TEXT, feed TEXT DEFAULT 'following', platform TEXT,
           author_id TEXT, first_seen_at INTEGER, last_seen_at INTEGER,
           PRIMARY KEY(item_id, feed));
following_runs(id INTEGER PRIMARY KEY AUTOINCREMENT, plugin TEXT,
               feed TEXT DEFAULT 'following', started_at INTEGER,
               finished_at INTEGER, ok INTEGER, count INTEGER,
               new_count INTEGER, error TEXT);
```

行为：

- `mark_feed_items` 用 UPSERT，`first_seen_at` 只在第一次插入时写，重复同步不会把旧内容顶成新的；
- `following_page` 的排序键是 `COALESCE(NULLIF(i.published_at, 0), f.first_seen_at)`。小红书笔记经常不给发布时间，按第一次看到的时间排，并返回 `time_estimated`，前端把这一组放在最后；
- `prune` 删完 items 会清掉孤儿 `item_feeds`，避免「N 条」虚高；
- 进程重启后 `recover_following_runs` 把没跑完的同步标成失败，关注页不会永远显示「正在同步」。

## 同步器

`onefeed/following.py` 的 `FollowingRunner` 与 `RefreshRunner` 分开：

- 每个平台单独事务，失败只影响自己，其他平台照常 `mark_feed_items`；
- 冷却从 `following_runs` 算，默认 300 秒，不受主信息流 `last_pull_at` 影响；
- `cancel(owner)` 只停排队中的平台，正在跑的当前平台会先跑完；
- 不写 `runs` 表，也不触发主信息流的 `reloadKey` / `refreshSeq`。

宿主只调用 `host.pull(plugin_id, feed_id='following', limit=...)`，插件返回什么就存什么。

## 四个插件的关注流

改动在插件仓库 `publieople/onefeed-plugins`（本地目录 `onefeed-plugins/plugins`）：

| 平台 | 版本 | 关注流入口 | 接口 |
|---|---|---|---|
| B 站 | 0.5.1 | `bili feed timeline` | 复用已有 timeline 动态 |
| 抖音 | 0.4.1 | `https://www.douyin.com/follow` | `/aweme/v1/web/follow/feed/`，取 `data[].aweme`，跳过直播/卡片位 |
| 小红书 | 0.4.1 | `/explore?channel_id=homefeed.follow` | 同时匹配 `/api/sns/web/v1/homefeed` 与 `/api/sns/v1/follow/feed` |
| 知乎 | 0.2.1 | `https://www.zhihu.com/follow` | `/api/v3/moments`，只收 target 为 article/answer 的条目 |

四个 manifest 都增加了 `feeds[].id = following`（`requiresAuth` / `personalized` 为 true）。
抓不到时插件抛明确错误：未登录说未登录、页面改版说页面改版，不返回空列表冒充「没有内容」。

## HTTP

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/following` | platform / kind / author / cursor / limit；返回 items、next、counts、total、platforms、syncing |
| POST | `/api/following/refresh` | platforms / force；运行中返回 409 `following_running` |
| GET | `/api/following/progress` | 关注流自己的进度快照 |
| POST | `/api/following/cancel` | 协作式取消排队平台 |

平台状态由 `installed / supported / logged_in / last_ok` 组合：没装、没有 following feed、需要登录、可用。登录判断先看 cookie 文件；浏览器型插件如果只有持久档案，不直接判成未登录，等同步失败且错误里明确提到登录才标 `need_login`。

## 页面

- `web/src/pages/FollowingPage.tsx`，路由 `/following`，lazy load；
- 顶栏品牌右侧「信息流 / 关注」两个 NavLink；
- 页头：同步按钮 + 进度胶囊（从按钮左侧出现，不占整行）；平台 chips 显示条数，需要登录的平台带警示；
- 三种布局：`list` 按日期分组的单列、`timeline` 按作者分组、`compact` 宽屏双列；
- 时间线的作者组按「该作者最近一条有发布时间的帖子」倒序，只有估算时间的作者排在最后；
- 未知发布时间统一放最后，组头写明「平台没给发布时间，按第一次看到的时间排」；
- 点条目走现有 `/item/:id`，带 `state.from = /following`，详情页的返回回到关注页；AI 总结、评论、收藏全部复用；
- 布局切换先本地生效，再 `PUT /api/settings { following_layout }`；设置页也能改默认值。

## 验证（2026-11-24 20:44，本机）

- `uv run python tests/run_all.py`：32 项全绿；新增 `tests/test_following.py` 4 组（分页/孤儿清理、同步与冷却、失败隔离与取消、API 与布局设置）；
- 插件解析桩：抖音去重/跳直播位、知乎只收回答文章/去重、小红书过滤非笔记/保留 xsec_token/未登录报错，8 项断言通过；
- 真机同步：四个平台各 12 条，共 48 条，新增 46 条（小红书、知乎各 1 条与信息流重叠），总耗时约 70 秒，四个平台 `last_ok=true`；
- 加载更多：首屏 30 条，翻到底 48 条，出现「这一页到底了」；
- 布局：时间线按作者分组、紧凑双列均能切换，`/api/settings` 的 `following_layout` 落盘；最后恢复 list；
- 详情：从关注页点 B 站动态进入详情，默认生成 AI 总结，点返回回到 `/following`；
- 期间主信息流顶栏没有出现关注同步进度，也没有首页刷新演出。

## 边界

- 只同步平台原生关注流，不提供 OneFeed 自建关注/作者页；
- v1 不做定时同步；首次打开且库里一条关注内容都没有时自动同步一次，之后手动；
- 平台不给发布时间的内容只能按首次看到时间排，页面明确标「时间未知」；
- B 站纯文字动态没有视频标题时，标题会退化成「动态」，正文在详情页；
- 小红书关注流接口尚未在登录态下长期验证，页面改版时插件会直接报错，不会静默空列表；
- 关注流每个平台仍受 `per_plugin_limit`（默认 12）限制，翻页靠 `item_feeds` 游标，不做无限滚动。
