# 关注名单、作者主页与直播过滤（2026-11-25）

关注流上线后（见 [following-2026-11-24.md](following-2026-11-24.md)），还差三件事：关注的人到底是谁、点作者能不能看他的主页、B 站直播动态混在流里点进去没内容。这次一起补齐。

## 1. 现在能做什么

- 顶栏「关注」页多了两个 tab：「动态」是原来关注的人发了什么；「关注的人」是名单本身。
- 关注名单目前只有 B 站能同步：登录态由本机 bili CLI 管理，同步一次拿到全部关注账号（实测 602 个，30.8 秒）。抖音、小红书、知乎的插件还没有名单接口，页面上明确写「暂不支持名单」，不假装空列表。
- 名单支持按平台筛选、按名字/简介/ID 搜索、加载更多。每行显示头像、名字、平台、简介、最近见到时间，整行点进作者主页。
- 作者主页 `/author/:platform/:accountId`：头像、名字、平台、是否已关注、简介、关注/粉丝/作品数、去平台主页、重新读名片；下面是该作者已入库的内容。
- B 站作者页可以「从平台补一页」：插件按 mid 拉作者视频（`bili user videos`），**只有第一次补进来的新条目**标 `author_only=1`，只出现在作者页，不进主信息流和关注流；如果同一条内容本来就在主信息流可见，作者页再抓一次也不会把它藏起来。
- 作者入口铺到三处：信息流卡片页脚的头像+名字、关注流每一行的作者名、详情页标题下的作者名。点进去都能按原路返回；「动态 / 关注的人」tab 写进 URL（`?tab=accounts`），从名单点作者再返回仍停在名单。
- B 站直播动态从源头过滤：插件跳过 `type=live`（含转发原动态是 live）；v11 迁移把存量 3 条旧直播标成 `is_live=1`；主信息流、关注流、搜索、计数都不再返回它们。直接打开旧链接时，详情页会说明「这是直播动态，不会进信息流」，并给去 B 站的链接。

## 2. 数据模型（schema v11）

### items 两个新列

```sql
is_live     INTEGER NOT NULL DEFAULT 0  -- 直播动态：先隐藏，不删数据
author_only INTEGER NOT NULL DEFAULT 0  -- 作者页远端补页：不进主信息流
```

迁移时除了 `ALTER TABLE`，还按 `extra LIKE '%"dynamic_type": "live"%'` 把老 B 站直播动态补标成 `is_live=1`。查询层在 `page / following_page / search_items / cluster_items / all_titles / count / platforms / following_counts / following_count` 统一过滤 `COALESCE(is_live,0)=0 AND COALESCE(author_only,0)=0`。作者页自己的 `author_items` 不过滤 `author_only`，但仍然过滤 `is_live` 和 hidden。

`upsert_items(items, preserve_hidden=True)` 用于作者页补页：如果同一条内容已经是 live 或 author_only，后来的普通写入不能把它翻回可见。主信息流同步仍用默认 `False`。

### following_accounts

```sql
CREATE TABLE following_accounts (
  platform      TEXT NOT NULL,
  account_id    TEXT NOT NULL,
  name          TEXT NOT NULL DEFAULT '',
  avatar        TEXT NOT NULL DEFAULT '',
  url           TEXT NOT NULL DEFAULT '',
  bio           TEXT NOT NULL DEFAULT '',
  relation      TEXT NOT NULL DEFAULT 'following',
  active        INTEGER NOT NULL DEFAULT 1,
  followed_at   INTEGER NOT NULL DEFAULT 0,
  first_seen_at INTEGER NOT NULL DEFAULT 0,
  last_seen_at  INTEGER NOT NULL DEFAULT 0,
  extra         TEXT NOT NULL DEFAULT '{}',
  PRIMARY KEY (platform, account_id)
);
```

- 关注名单与关注流是两张表：前者按账号存，后者按内容存。同一个人最近没发东西，也还能在名单里找到；内容被 prune 掉，不会把关注关系一起删掉。
- `active` 只表示「上一次完整同步时还在名单里」。完整同步时本轮没返回的人标 `active=0`，不删；本轮返回空列表时不动旧记录，避免登录失效把整张表清空。
- 空 name/avatar/url/bio 不覆盖旧值；`followed_at` 只在大于 0 时更新；`extra` 非空才覆盖。

## 3. 同步器与插件契约

### AccountsRunner

`onefeed/following.py` 里新增 `AccountsRunner`，和 `FollowingRunner` 完全分开：

- `ACCOUNTS_FEED="accounts"`、冷却 30 分钟、失败隔离、每平台独立 `start_following_run/finish_following_run`。
- 只拉名单，不写主信息流，不触发顶栏刷新进度。
- 每页 50 个，最多 20 页 / 1000 人；遇到 next 为空就停。
- 服务重启时 `recover_following_runs("accounts")` 把没跑完的记录标 interrupted。

### 插件新方法

宿主 `plugin_runtime/host.py` 增加：

- `following_accounts(plugin_id, cursor, limit)`：要求 manifest features 含 `following_accounts`；调 worker 的 `followingAccounts`；按 `account_id` 去重。
- `author_profile(plugin_id, account_id)`：要求 `author_posts`；调 `authorProfile`；白名单 name/avatar/bio/url/following/follower/posts。
- `author_posts(plugin_id, account_id, cursor, limit)`：调 `authorPosts`；用 `to_item` 归一化，按 `published_at` 倒序。

manifest 的 `FEATURES` 同步增加 `following_accounts` 与 `author_posts`，否则市场清单校验不过。

### B 站插件 0.6.0

- `plugin.json` 增加 `http` 能力、`cookieFile` 设置、`following_accounts/author_posts` feature，`cli.allow` 增加 `bili me` 与 `bili user`。
- 关注名单走 `GET https://api.bilibili.com/x/relation/followings?vmid=<mid>&pn=<page>&ps=50&order=desc`。mid 从 `bili me show --raw` 取，不需要 Wbi。
- B 站接口只认大写 cookie 名（SESSDATA/DedeUserID），而 bili CLI 落盘的是小写键。宿主 HTTP 能力新增 `cookieCase` 选项（keep/upper/lower），并把 `cookieFile` 里的 `${state}` 用 `_expand` 展开；B 站插件传 `cookieCase: "upper"`。
- 作者名片用 `bili user info <mid> --raw`，作者视频用 `bili user videos <mid> --raw --page N --size limit`。
- `pullTimeline` 过滤 live：`row.type`、`row.original.type`、`row.live`、`row.original.live` 任一命中就跳过。

## 4. HTTP API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/following/accounts` | 名单分页：platform（逗号分隔）、q、limit 1–1000、offset；返回 accounts/next/count/total/platforms/plugin_errors/counts/syncing/progress |
| POST | `/api/following/accounts/refresh` | 触发名单同步；运行中 409 `accounts_running` |
| GET | `/api/following/accounts/progress` | 名单同步进度 |
| POST | `/api/following/accounts/cancel` | 取消名单同步 |
| GET | `/api/authors/{platform}/{account_id}` | 作者名片 + 本地作品；refresh=1 重读名片 |
| GET | `/api/authors/{platform}/{account_id}/posts` | 本地作者作品分页 |
| POST | `/api/authors/{platform}/{account_id}/fetch` | 从平台补一页，写 author_only |

平台状态由 `installed/supported/logged_in/last_ok` 组合成 `not_installed / unsupported / need_login / ready`。B 站登录探测看 bili CLI 凭证；其他平台若只有浏览器档案，`logged_in` 返回 `null`，等同步时再验证。

## 5. 页面

- 关注页 `/following`：header 下新增「动态 / 关注的人」tab，tab 状态读写 URL 的 `tab` 参数。动态 tab 保持原来的三布局；名单 tab 用独立组件 `FollowingAccounts.tsx`。
- 名单首次打开且 total=0、又有 ready 平台时，自动同步一次；之后手动「同步名单」。同步按钮左侧长出的进度胶囊与主信息流那套一致，不占整行。
- 名单里的 unsupported 平台合成一行说明，不再每个平台刷一条警告；失败/需要登录才用黄色警告条。
- 作者主页 `AuthorPage.tsx`：本地 0 条且平台支持远端时自动补一页；「从平台补一页」按钮可继续翻页，next 为空就停。非 B 站或插件没有 `author_posts` 时明确写「这个平台暂时不能补历史作品」，不转圈。
- 作者链接：`Card.tsx` 的作者区必须加 `pointer-events-auto relative z-10`，因为卡片内容层整体是 `pointer-events-none`，铺满卡片的 stretched link 才会接点击；不加就还是会打开详情页。
- 详情页旧的直播条目顶部显示说明卡片，不删数据、不 404。
- 作者名片的回写只针对名单里已有的账号：未关注作者只是临时查看，不会因为读了一次名片就被写进 `following_accounts`。

## 6. 验证（2026-11-25，本机 8787）

- 数据库迁移：旧库 `user_version 10 → 11`，3 条 B 站直播标成 `is_live=1`；主信息流 1637 条（B 站可见 300 条）。
- 关注名单：B 站同步 602 个账号，30.8 秒；接口返回分页正常；`following_accounts` 有 602 行。
- 关注流：B 站重新同步 33 条动态，页面返回 `live-in-page=[]`，确认直播不再进流。
- 作者页：B 站作者 585267 自动补 30 条作品；第二页 `cursor=2` 返回 5 条、next=3；这些条目 `author_only=1`，`store.count()` 不变（不影响主信息流）。
- 页面：关注名单 602 个账号正常渲染/搜索/平台筛选；信息流卡片作者、关注流作者名、详情页作者名三处都能进作者页；旧直播条目说明卡正常显示。
- 提交前审 diff 收口三处：作者页补页不再误伤主信息流可见性；读未关注作者名片不再写入关注名单；信息流/关注流的作者跳转带 `from`，关注页 tab 进 URL。`test_following.py` 增加「作者页重抓已在主信息流可见的条目仍可见」和「陌生人读名片不写名单」两条断言。
- 测试：`uv run python tests/run_all.py` 32 项全部通过（`test_following.py` 6 组）。
- 构建：`npm run build` 通过，`index-IMhaAnUX.js` 473.61 kB / gzip 150.48 kB，`AuthorPage-D1Vd0x8R.js` 8.34 kB，`FollowingPage-DaEySJD3.js` 25.33 kB。

## 7. 边界

- 关注名单目前只有 B 站。抖音、小红书、知乎要做名单，得先解决各自的签名/浏览器私有接口；现在诚实显示「暂不支持名单」。
- 作者远端补历史作品目前只有 B 站。其他平台的作者页只显示已经入库的内容。
- 名单同步是手动的（首次空表自动一次），没有定时任务；关注流的定时同步也还没做。
- B 站直播只从流里隐藏，数据保留；以后要做直播卡片可以直接用 `is_live`。
- 旧直播条目仍会触发现有 AI 总结（会返回「可提取内容不足」）；说明卡已经讲清楚原因，后续可以让它直接跳过总结。
- 关注名单是「本人账号关注了谁」，不是 OneFeed 自建关注列表；自建关注以后另做。
