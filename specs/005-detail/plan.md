# 005 详情页实施计划

对应 spec：`specs/005-detail/spec.md`
开始：2026-11-16　宿主版本目标：0.3.0

## 0. 本轮先落地（与方案无关的顺手修）

- [x] T30a 评论多余提示清理：`onefeed/api.py:194-228` 去掉两条 hint；`web/src/components/Drawer.tsx:286-290` 不再渲染 hint，只留 reason。构建 + 测试 + 截图验证后提交。

## 1. P1：能播、能读（6–8 h）

### T31 存储层：details 表（45 min）
- `onefeed/store.py`：`SCHEMA_VERSION = 3`，`SCHEMA` 追加 details 表（见 spec §3.4）。
- 新方法：`get_detail(item_id) -> dict | None`、`save_detail(item_id, payload)`、`drop_detail(item_id)`。
- 迁移写在 `_migrate()`（`CREATE TABLE IF NOT EXISTS` 本身就幂等，不再单独写迁移脚本）。
- 单测 `tests/test_store.py`：save → get 往返；过期判断；覆盖写。

### T32 运行时：host.detail()（60 min）
- `plugin_runtime/host.py`：加 `detail(plugin_id, item) -> dict`，超时用已预留的 `DEFAULT_TIMEOUTS["detail"]`（92s）。
- 复用 `run()` 的子进程机制；结果做**字段白名单**校验（只留 body/media/images/stats/note，丢弃其他键），防止插件塞奇怪字段进前端。
- `manifest.py`：`FEATURES = {"comments", "detail", "media"}`；`embeds`、`mediaHosts` 两个可选字段解析与校验（`mediaHosts` 只允许 `*.domain` 或精确 host，拒 `*`）。
- 单测 `tests/test_manifest.py` 补 4 条：features 解析、mediaHosts 非法值报错、embeds 缺省为空、旧 manifest 不声明也能加载。

### T33 API：详情接口（45 min）
- `onefeed/api.py` 新增 `GET /api/item/{item_id}/detail`：
  - 未声明 → `{"supported": false, "reason": "<plugin> 的插件没有提供详情接口"}`
  - 命中缓存且未过期且非 refresh → `{supported, detail, from_cache: True}`
  - 否则调 `host.detail` → `store.save_detail` → 返回
  - 异常 → `{"supported": true, "error": message[:300]}`（对齐评论接口风格，不加 hint）
- 单测 `tests/test_api.py`：4 条（未支持 / 缓存命中 / 强刷 / 插件抛错）。

### T34 边车：/api/media（90 min）
- `onefeed/media.py`（新文件）：`resolve_slot(detail, slot) -> (url, headers)`；`stream(url, headers, range_header) -> (status, headers, iterator)`。
- 路由 `GET /api/media/{item_id}/{slot}`：slot 白名单 `video|poster|img-\d+`；URL 只从 details 表取。
- 凭证注入：host 匹配插件 `mediaHosts` 才加 `Cookie`；始终加 `Referer`（插件给）与固定 UA；重定向跨域时丢弃 Cookie。
- Range 透传；`Cache-Control: private, max-age=0`；单条并发 4 个信号量。
- 单测 `tests/test_media.py`：白名单外不注入 Cookie（AC-D8）、slot 越界 400、详情不存在 404。

### T35 插件：bilibili 0.3.0（40 min）
- `onefeed-plugins/plugins/bilibili/index.js` 加 `detail()`：`ctx.cli.run(["bili","video","info",bv,"--raw"])` → 简介/统计/时长；`media = {type:"embed", embedUrl:"https://player.bilibili.com/player.html?bvid=<bv>&page=1&autoplay=0"}`；`body = {kind:"text", value: 简介}`。
- `plugin.json`：`features: ["comments","detail","media"]`、`embeds:["bilibili"]`、`mediaHosts:["*.hdslb.com","*.bilibili.com"]`、version 0.3.0。

### T36 插件：v2ex 0.2.0（30 min）
- `detail()`：`ctx.http.request({url:"https://www.v2ex.com/api/topics/show.json", query:{id: nativeId}})` → 数组取 [0]，`body = {kind:"html", value: content_rendered}`（已是安全 HTML，仍走前端净化）。
- 回复数：`replies` 是整数，不当作数组用；详情页评论区仍走 comments 能力（V2EX 没实现，显示「v2ex 的插件没有提供评论接口」）。

### T37 插件：掘金 0.2.0（40 min）
- `detail()`：`ctx.http.request({url:"https://juejin.cn/post/<id>"})` → 正则截 `<article …>…</article>`（实测 24KB HTML / 13KB 正文）。
- 正文里 `<img src>` 保持原样（前端会改写走边车）；`body = {kind:"html", value: articleHtml}`。
- 失败兜底：截不到 `<article>` 时返回 `{body:{kind:"text", value: item.text}}`，不抛错。

### T38 前端：详情页骨架（150 min）
- 新文件 `web/src/pages/ItemPage.tsx`；`App.tsx` 加 `<Route path="/item/:id" element={<ItemPage ctx={ctx} />} />`。
- `FeedPage.tsx:135`：`onOpen={(id) => navigate(\`/item/\${id}\`)}`。
- 结构：返回按钮 / 平台 chip / 标题 / 作者行 / 统计块（复用 `VIEW_LABEL`）/ 媒体区 / 正文 / 标签 / 同题其他平台 / 评论 / 底部「去原帖 + 复制链接」。
- 首屏先用 `/api/item/{id}` 的数据渲染，再异步取 `/detail`（skeleton 占位）。
- `web/src/api.ts`：加 `DetailResponse`、`getDetail(id, refresh?)`。
- 视频区：embed → iframe；file → `<video controls preload="metadata" poster="/api/media/<id>/poster">`。
- 正文区：text 先用 `white-space: pre-wrap`；html 留到 T39 净化后接。

### T39 净化与图文（90 min，可并入 P1 末尾）
- `npm i dompurify`（+ `@types/dompurify` 若需要）；`web/src/lib/sanitize.ts` 白名单：`h1-h4,p,ul,ol,li,pre,code,blockquote,img,a,strong,em,br,hr,table,thead,tbody,tr,td,th`；属性只留 `href,src,alt,title`；`a` 强制 `target=_blank rel="noreferrer"`。
- 正文 `img` 的 src 统一改写为 `/api/media/<id>/img-<n>`，按正文里出现顺序在渲染时收集。
- 图文画廊：大图 + 缩略条 + 灯箱（左右键/点击遮罩关闭）。

## 2. P2：补齐（3–4 h）

- [ ] T40 抖音 pull 保留 `play_addr`（`extra.play_url` / `extra.play_expires`），detail 先读 extra，读不到再 capture。
- [ ] T41 知乎热榜 `kind=list` 详情卡：标题 + 热度名次 + 「去知乎看」，不生成任何假正文。
- [ ] T42 详情页「评论」块与「同题兄弟」块从 `Drawer.tsx` 抽出成 `components/Comments.tsx`、`components/Siblings.tsx`，页面与抽屉共用。

## 3. P3：最难的两个（4–5 h）

- [ ] T43 小红书 detail：`ctx.browser.capture({url: item.url, patterns:["/api/sns/web/v1/feed"]})` → `note_card` 的 `desc`（正文）、`image_list`（图）、`video.media.stream.h264[0].master_url`（视频直链）；媒体走边车（`mediaHosts` 加 `*.xhscdn.com`）。
- [ ] T44 抖音 detail 兜底：capture `/aweme/v1/web/aweme/detail/`；直链 403 时自动重取一次，仍失败降级「去原帖」。
- [ ] T45 抽屉下线：删除 `Drawer.tsx` 与 `FeedPage` 里的 drawer 状态；`?peek=1` 重定向到 `/item/:id`。
- [ ] T46 过期与降级：`expiresAt` 到时前端自动 `refresh=1` 一次；失败显示灰字重试。

## 4. 测试与验收

后端：`uv run python tests/run_all.py --offline`（现有 6 组 + 新增 detail 3 组）。
前端：`cd web && npm run build`（tsc 严格模式必须过）。
手工验收（对着 AC-D1…D8 跑一遍，截图存 `design/detail-*.png`）：

1. `/item/bilibili:video:BV15Gsj6iEaz` → 页面内播放，不跳转。
2. `/item/v2ex:topic:1257214` → 正文 900+ 字，评论区显示「v2ex 的插件没有提供评论接口」。
3. `/item/juejin:article:7707927071724486665` → 正文 + 图片，无 `<script>` 残留（`document.querySelectorAll('script')` 检查）。
4. `/item/zhihu-hot:hot:…` → 摘要卡 + 去原帖，不报错。
5. 拔网线刷新详情 → 灰字重试 + 去原帖，白屏算失败。

## 5. 提交与发布节奏

| 提交 | 内容 | 门禁 |
| --- | --- | --- |
| commit 1 | 评论提示清理（T30a） | build + 六组测试 + 截图 |
| commit 2 | details 表 + host.detail + manifest（T31/T32） | 单测通过 |
| commit 3 | /detail + /media（T33/T34） | 单测 + 手工 curl Range |
| commit 4 | 三个插件 detail + 版本号（T35-T37） | `scripts/validate.py` 6/6 |
| commit 5 | 详情页前端（T38/T39） | `npm run build` + 三张截图 |
| commit 6 | P2/P3 分批 | 逐条 AC |

回滚：前端回滚只需去掉路由并恢复 `onOpen={setDrawer}`；后端 details 表保留即无害（旧代码不读）。插件降级：把 `features` 里的 `detail` 删掉，宿主立即退回卡片态。

## 6. 时间预算（对准 11-28）

- 11-16 晚：commit 1 + P1 后端（T31–T34）。
- 11-17：P1 三个插件 + 详情页骨架，跑通 B 站/V2EX。
- 11-18：P2，掘金正文和图文画廊。
- 11-20 前：P3 小红书/抖音，能通则演示时多两个平台，不能通则按 AC-D7 降级，不阻塞主链路。

## 7. 交付状态（2026-11-16）

P1 已落地并实测，T43 的小红书与 T44 的抖音按等价方案提前做了（不需要 capture）：

- [x] T31 details 表：`SCHEMA_VERSION = 3`，`get_detail(item_id, max_age)` / `save_detail` / `drop_detail`；`tests/test_store.py` 37 项（含过期与删除）。
- [x] T32 `PluginHost.detail()`：复用子进程，超时 `DEFAULT_TIMEOUTS["detail"]=92.0`，结果只留 `body/media/images/stats/note`；manifest 新增 `features`（comments/detail/media）与 `mediaHosts`。
- [x] T33 `GET /api/item/{item_id}/detail`：未声明 → `{supported:false, reason:"<plugin> 的插件没有提供详情接口"}`；缓存 6h；`refresh=1` 强制重取；异常只回 `error`，不带 hint。
- [x] T34 `GET /api/media/{item_id}/{slot}`（`onefeed/media.py`）：slot 白名单 `video|poster|img-\d+`，URL 只从 details 表取；Range 透传；命中 `mediaHosts` 才注 Cookie；实测 `206 video/mp4` / `206 image/webp` / 不存在 404。
- [x] T35 bilibili 0.3.0：`bili video info <bv> --raw` + `player.bilibili.com/player.html?bvid=` embed；`mediaHosts ["*.hdslb.com","*.bilibili.com"]`。
- [x] T36 v2ex 0.2.0：`/api/topics/show.json?id=` 的 `content_rendered` 作 html body。
- [x] T37 掘金 0.2.0：抓 `juejin.cn/post/<id>` 截 `<article>`，去掉复制过来的 `<meta>`、`<h1>` 标题与作者块（页面上已经显示过）。
- [x] T43 小红书 0.3.0（替代 capture 方案）：`ctx.browser.extract({name:"xhs.note"})` 读页内 `__INITIAL_STATE__`（`undefined` / `new Map([])` 字面量没法当 JSON 解析，只能在浏览器里 evaluate）；`media.referer` 让直链走边车（浏览器带本地 Referer 会被 xhscdn 403）；`mediaHosts ["*.xhscdn.com"]`。
- [x] T44 抖音 0.2.0（替代 capture 方案）：`open.douyin.com/player/video?vid=<aweme_id>` 官方播放器 embed，不抓详情、不碰签名。
- [x] T38 `web/src/pages/ItemPage.tsx` + `App.tsx` 的 `/item/:id`；`FeedPage` 卡片改为 `navigate`。
- [x] T39 DOMPurify 净化 html 正文；图片走 `/api/media/<id>/img-N`；单图居中大图、多图网格 + 灯箱；视频笔记不重复铺封面。

未做（P2/P3 余项）：T42 抽 `Comments`/`Siblings` 组件、T46 `expiresAt` 自动刷新。（原列的 T40/T41/T45 已于 2026-11-17 完成，见第 8 节。）

验收证据（`design/`）：`detail-feed-entry.png`、`detail-bilibili-top.png`、`detail-bilibili-comments.png`、`detail-douyin-player.png`、`detail-xhs-video.png`、`detail-xhs-body.png`、`detail-xhs-images.png`、`detail-juejin.png`、`detail-v2ex.png`、`detail-zhihu-fallback.png`。

测试：`uv run python tests/run_all.py --offline`（store 37 / api 24 / settings 31 / auth 5 / market 44 / entry 7 全过）、`cd web && npm run build` 通过、`scripts/validate.py` 6/6。

实际耗时：T31–T39 约 5 小时（含小红书 403 排查与掘金去头），比 P1 预算 6–8h 略快；剩下的 P2/P3 里只有 T45（抽屉下线）会影响演示观感，建议在彩排前处理。

## 8. 交付状态（2026-11-17）：T40 / T41 / T45

- [x] T40 抖音 `pull` 保留 `play_addr`：`awemeItem()` 把网页端直链存进 `extra.play_addr`;详情里同时给 `media.fallbackUrl` + `media.fallbackReferer`。宿主 `_normalize_media`（embed 分支）透传这两个字段（仍是白名单，且有 `embeds` 校验）；`media.resolve_slot("video")` 对 embed 型回兜底直链，边车照旧补 Referer。前端 `ItemPage` 的 embed 播放器下面多一个「播放器打不开？换直链播放」开关。实测 `/api/media/<id>/video` 带 Range → `206 video/mp4, content-range bytes 0-2047/14279234`，点开关后 video 正常播放（`design/detail-douyin-fallback.png`）。
- [x] T41 知乎热榜详情卡：zhihu-hot 0.2.0，capabilities 加 `browser`、features 加 `detail`，详情调宿主内置提取器 `ctx.browser.extract({name:"zhihu.question"})`；问题描述（页面数据里是 HTML 片段）先 strip 成纯文本再分段，回答正文保留 HTML 交给 DOMPurify，只列赞数前 5 条。实测 22s 出 5085 字正文 + `stats {view:5200000, answer:456, comment:38}`（`design/detail-zhihu-hot.png`、`design/detail-zhihu-answers.png`）。
- [x] T45 抽屉下线：`CommentBody` 迁到 `web/src/components/CommentBody.tsx`，`Drawer.tsx` 删除（全站只有 ItemPage 还引用它）。
- [x] 顺手：`ItemPage` 统计卡补 `answer` → 「回答」，否则知乎这类只有问答数的地方会被过滤掉。
- [x] 测试：新增 `tests/test_media.py`（15 项：video/poster/img-N 解析、embed 兜底直链透传、白名单外字段丢弃），`run_all.py` 加进 ORDER；离线七组全过（store 37 / api 24 / settings 31 / auth 5 / market 44 / media 15 / entry 7）。

## 9. 知乎登录态推荐流（2026-11-17）

- 登录：宿主 `onefeed/auth.py` 的 `SPECS` 里有 `zhihu`（domain `.zhihu.com`，判据 `z_c0`）。扫码成功后 16 条 cookie 落到 `.onefeed/cookies/zhihu.json`；**插件 id 必须叫 `zhihu`**，宿主是按插件 id 找这个文件的。
- 取数：`onefeed-plugins/plugins/zhihu` 用 `ctx.browser.capture` 回放 `/api/v3/feed/topstory/recommend`（`x-zse-96` 由页面自己算，纯 HTTP 带 cookie 也是 401）。`scroll {times:8, dy:3000, intervalMs:2200}` + `stopWhenMatched:false`，一屏拿 8 个响应 × 6 条，按 `type:id` 去重后 40 条 / 27s。
- 详情：`plugin_runtime/capabilities.py` 新增 `zhihu.article` 提取器（读 `initialState.entities.articles`），和既有 `zhihu.question` 配对；插件按 `extra.zhihu_type` 选一个，`ctx.browser.extract` 取 `js-initialData` 里的正文 HTML 交给 DOMPurify。实测回答页 7.5s / 3603 字，专栏页 7.7s / 4344 字。
- 前端：`platform.ts` 注册 `zhihu` 与 `zhihu-hot`（原先两个都显示「知乎」）；`Card.tsx` 里无封面的 article/video 走摘要文字面板并提示「点开看全文」；`ItemPage` 对 html 正文隐藏知乎空段落（`p.ztext-empty-paragraph` / `p` 内只有 `br`），段距不再被撑开。
- 证据：`design/zhihu-feed.png`（推荐流筛选视图）、`design/zhihu-detail.png`（专栏全文带图）。
- 未做：关注流 `/api/v3/moments`（同一套回放机制，多一个 pattern 即可）。

## 10. 评论区：知乎 comment_v5 回放 + 跨进程 profile 锁（2026-11-17）

- 接口不是纯 HTTP 能算的：`/api/v4/comment_v5/questions/{问题id}/root_comment` 与 `/api/v4/comment_v5/articles/{文章id}/root_comment`，签名由页面现算。回答页按**问题**聚合评论，不是 answer id。
- 触发方式两种：专栏页滚屏就自己加载；回答页必须点「N 条评论」按钮才发请求。所以 `browser.capture` 新增 `click`（滚完屏依次点的选择器，最多 4 个）与 `scrollPoint`（评论弹层自己吞滚轮，滚之前得把鼠标挪进弹层）两个可选参数。
- 响应字段：`counts.total_counts` 总数、`data[].id/content(HTML)/author/like_count`、`created_time`（**秒**，与前端 `timeAgo` 一致）、`child_comment_count`；`vote_count` 是 null 不能用。
- 插件 `zhihu` 0.2.0 新增 `comments()`：按 `extra.zhihu_type` 决定点不点按钮，合并多个响应按 comment id 去重，空结果抛可读错误。
- 修并发 bug：详情与评论会同时请求，两边都要用同一个 Chrome user-data-dir。插件跑在各自 worker 子进程里，进程内线程锁拦不住，改成 profile 目录下的文件锁 `_ProfileGuard`（Windows `msvcrt.locking`，非 Windows `fcntl.flock`）。
- 实测：回答 18 条 / 23.5–24.9s；专栏 4 条 / 14.6–19.9s（同 URL 探针能拿 9 条，插件注入登录态后只给 4 条，差异未查明，接受）。并发请求串行后总计 28.3s。
- 证据：`design/zhihu-comments.png`。

## 11. 评论分页：先看几条，滚到底再要（2026-11-17）

- 目的：一进详情页就把几十条评论全渲染出来既慢又没意义。改成折叠 5 条 + 「查看更多评论（共 N 条）」，点开后滚到底自动要下一页，要不到时给一句去原站的引导。
- 契约：`host.comments(plugin_id, item, limit=20, cursor=None)` 返回 `{items, next}`（老插件直接返回数组仍然兼容，`next` 视为 None）。`GET /api/item/{id}/comments` 新增 `cursor` 参数，缓存键变成 `(item_id, limit, cursor)`；异常分支同样带 `next: null`。
- 插件：B 站 `comments()` 把 `cursor` 当页码（`bili comment list --page`，上限 20）；第 2 页起失败按 `{items: [], next: null}` 吞掉——那些页要登录态，不该把评论区打红。知乎评论是页面按滚轮拉的，拿不到可复用游标，只出第一页（`next: null`）。
- 前端：`COLLAPSED_COMMENTS = 5`；`commentTailVisible = expanded || 条数 <= 5`，所以评论本来就只有几条时也照样显示尾部那句「插件能读到的评论就这些（N 条）。全部评论去 X 看原帖」。`IntersectionObserver`（rootMargin 240px）负责滚动加载，按评论 id 去重合并，失败即置 `next = null` 以免无限重试。
- 实测：B 站 `BV1GDsW6XErJ` 首页 20 条 `next: "2"`，`cursor=2` 再拿 20 条 `next: "3"`；知乎专栏 4 条 `next: null`，页面直接全显示并给出引导。
- 证据：`design/comments-collapsed.png`（折叠 5 条 + 查看更多）、`design/comments-loadmore.png`（滚动后追加第 2 页）、`design/comments-exhausted.png`（知乎 4 条时的去原站提示）。

## 12. 抖音 / 小红书评论（2026-11-17）

- 抖音（插件 0.4.0，features 补 `comments`）：接口是 `/aweme/v1/web/comment/list/`，签名由页面算，只能回放。**未登录时评论区只给第一页 5 条**，接着页面就显示「请先登录后发表评论」，再滚也不发新请求（响应里 `total: 2117`、`has_more: 1`，但拿不到第二页）。所以插件滚 6 次把能拿的合并（按 `cid` 去重），返回 `next: null`，前端自然显示「插件能读到的评论就这些（已取 5 条）。全部评论去抖音看原帖」。要更多得先用宿主登录窗口扫码登录抖音（`.onefeed/cookies/douyin.json` 目前不存在）。
- 抖音字段：`comments[].cid/text/user.nickname/digg_count/reply_comment_total/create_time`（**秒**）、楼中楼在 `reply_comment`（列表里常为空，取前 3 条映射进 `replies`）。
- 小红书（插件 0.4.0，features 补 `comments`）：接口 `/api/sns/web/v2/comment/page?note_id=&cursor=&xsec_token=`，cursor 是页面自己算的 opaque 值，插件无法直接续。做法是首轮 `capture` 一次滚到底（`scroll {times:10, dy:1100, intervalMs:1000}`，**必须 `scrollPoint {x:1180,y:620}` 把鼠标移进右侧评论列**，否则滚轮只滚正文、一个评论请求都不发），抓到的整批存进 `ctx.cache`（10 分钟），`cursor` 当 offset 切片；翻页直接命中缓存，不再重开浏览器。
- 小红书字段：`data.comments[].id/content/user_info.nickname/like_count`（**字符串**）`/sub_comment_count/create_time`（**毫秒**，除 1000）、楼中楼在 `sub_comments`。
- 实测：抖音未登录 5 条 / 12.0s；小红书首屏 18.2s → 20 条 `next: "20"`，第二页走缓存 0.5s → 16 条 `next: null`（这批共 36 条），第 4 页越界返回 0 条。
- 前端文案跟着改准：「查看更多评论（共 N 条）」→「已取 N 条」，尾部同样说「已取 N 条」，因为插件能翻到的总数和首页 `count` 不是一回事。
- 证据：`design/comments-douyin.png`（5 条 + 去原站）、`design/comments-xhs-collapsed.png`（折叠 5 条 + 查看更多（已取 20 条））、`design/comments-xhs-exhausted.png`（展开后滚到 36 条 + 提示）。

## 13. 图文灯箱：贴视口、能缩放（2026-11-18）

小红书图文笔记的图片点开后以前会「占满整个详情页」：图被拉到几千像素高，只能看到左上角一截，滚动也救不回来。

- 根因：灯箱是 `fixed inset-0` 直接写在 `.page-shell` 里。路由的 `motion.div` 带 `transform`，会让后代的 `position: fixed` 以整页（而不是视口）为包含块，覆盖层高度变成文档高度，`img max-h-full` 自然按整页算。这与早前「AI 胶囊跑到页面最底下看不见」是同一个坑。
- 修法：灯箱抽成 `Lightbox` 组件，用 `createPortal(..., document.body)` 挂到 `body`；容器 `fixed inset-0 z-[60] flex flex-col bg-black/90`；顶部一行「N / M · 点图看原尺寸」+ 关闭；内容区 `flex-1 overflow-auto` 居中放图，默认 `max-h-[calc(100dvh-96px)] max-w-full object-contain`（整张可见），点图切到原始尺寸 `w-[min(94vw,1200px)] max-w-none` 允许滚动看细节；多于一张时显左右箭头。
- 键盘与滚动：`Esc` 关，`←`/`→` 翻页；打开时 `body.style.overflow = "hidden"`，关闭恢复原值（记录 prev，避免踩掉别处的锁）。
- 同一类问题的全站排查：`.page-shell` 内不再有任何 `fixed` 子元素（探针数出来 0），AI 胶囊、设置页保存条、toast 早就都走了 `createPortal`。
- 验收 `probes/check_lightbox.py`（12 项）：灯箱不在 `.page-shell` 里、overlay 尺寸等于视口 `[0,0,1440,900]`、图高 ≤ 900、body 锁滚动、放大后宽度 ≤ 视口且可滚、`Esc` 关闭并恢复滚动、左右键真的换图（`img-0` → `img-1`）、页壳内 fixed 元素为 0、390×844 手机视口下 overlay 贴视口且图 358×487 不出屏、无 `pageerror`。
- 静态回归 `tests/test_lightbox.py`（8 项）：`createPortal` 到 `document.body`、`fixed inset-0 z-[60]`、锁滚动的两处赋值、`cursor-zoom-in/out`、`ArrowLeft/ArrowRight`、默认 `max-h-[70vh]` 兜底。
- 证据：`design/lightbox-fit.png`（整张可见）、`lightbox-zoom.png`（原始尺寸）、`lightbox-phone.png`（手机视口）。

