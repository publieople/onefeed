# 还能接哪些平台 —— 2026-11-13 实测记录

> 目的：回答「除了 B 站 / 小红书 / 抖音，还有哪些平台接起来便宜」。
> 所有结论都是本机当场跑出来的，不是看文档猜的。抓数时间 2026-11-13 20:40–20:55（Asia/Shanghai）。

## 一句话结论

**六个平台已经全部跑通**（B 站、抖音、小红书、掘金、V2EX、知乎热榜）。
其中三个是**纯 HTTP 免登录**，每个 adapter 不到 50 行，这是性价比最高的扩平台方式；
真正难的从来不是「接多少平台」，而是「接进来的是不是你的个性化流」。

## 分级表

### A 级：免登录纯 HTTP，最便宜（实测全部 200）

| 平台 | 接口 | 实测 | 成本 | 拿到什么 |
|---|---|---|---|---|
| 掘金 | `POST api.juejin.cn/recommend_api/v1/article/recommend_all_feed` | 200 / 87KB / 453ms | ~40 行 | 推荐流 20 条：标题、作者、封面、阅读/点赞/评论/收藏、标签 |
| V2EX | `GET www.v2ex.com/api/topics/hot.json` | 直连超时；**走 `127.0.0.1:7890` 代理 200 / 47KB / 0.38s** | ~40 行 | 热帖 20 条：标题、节点、作者、回复数（无封面） |
| 知乎日报 | `GET news-at.zhihu.com/api/4/news/latest` | 200 / 2.5KB | ~30 行 | 当日 4 条：标题、配图、摘要（无互动数据） |

A 级的特点：**没有登录态、没有签名、没有风控**，失败率接近 0，适合当「演示兜底」。
缺点也明显：这些是「平台推荐」，不是「你关注的人」。

### B 级：CLI 现成，登录后可用

| 平台 | 工具 | 状态 | 说明 |
|---|---|---|---|
| B 站 | `bili 0.8.0` | ✅ 已登录 Publieople（mid 324858924），feed recommend 个性化 30 条 + 封面 + 评论楼中楼 | 唯一「登录态开箱可用」的平台 |
| 小红书 | 宿主 `browser`（截 `/api/sns/web/v1/homefeed`） | ✅ 已登录并跑通（2026-11-14）：注入 cookie 后一屏 29 条，带封面/点赞/作者；不再依赖 `xhs` CLI | 详情链接必须带 `xsec_token` |
| 抖音 | 自研 `douyin_browser` adapter（浏览器回放） | ✅ 免登录即出 20 条，登录后是个性化流 | 不走 CLI，见 `DY_FEED_FINDINGS.md` |

### C 级：浏览器回放能接，但要写第二个 adapter

| 平台 | 机制 | 判断 |
|---|---|---|
| 快手 | 与抖音同款：web 端 XHR + 签名，需要 headed 浏览器持登录态 | 技术上完全可行，但要再写 200 行 + 调试登录，**黑客松周期内不划算** |
| 微博 | `m.weibo.cn` 的 container API 是纯 JSON，登录 cookie 即可，无签名 | 比快手便宜，但内容质量与「AI × 校园」选题不搭 |
| 知乎（关注流） | `x-zse-96` 签名 + 登录 cookie，浏览器回放可解 | 投入等同抖音，收益是同质化图文 |

### D 级：明确不接（已实测失败或成本离谱）

| 平台 | 实测结果 | 结论 |
|---|---|---|
| 知乎热榜 API | `401 {"error":{"code":101,"name":"AuthenticationError"}}` | 需要登录态 + 签名，不如直接接日报 |
| 微博热搜 API | `403 {"error":"Forbidden"}` | 需要 cookie，公开接口已关 |
| 36 氪 RSS | `36kr.com/feed` 返回 HTML 首页 | RSS 已废弃，别再试 |
| 微信公众号 | 无公开接口，需第三方 wechat2rss 类服务 | 依赖外部服务，路演现场是风险点 |
| YouTube / X | 需代理 + 登录（X 还有反爬） | 与「国内校园日常」场景无关 |

### 补充：RSS 是一条万能后路（实测可读）

| 源 | 实测 |
|---|---|
| IT 之家 `ithome.com/rss/` | 200，标准 RSS 2.0 |
| 爱范儿 `ifanr.com/feed` | 200，标准 RSS |
| 少数派 `sspai.com/feed` | 200（仅 4.2KB，条目偏少） |
| Telegram 频道 `t.me/s/<channel>` | 200，HTML 里能直接抠出消息（无 API key） |
| Hacker News `hacker-news.firebaseio.com/v0/topstories.json` | 200 |

如果只想「多几个平台 chip」，加一个通用 RSS adapter（feedparser，30 行）就能一次接入上面所有源。

## 我的建议

1. **主线保持三个平台**（B 站 + 抖音 + 小红书）。这三个才是「你的信息流」，也是路演里「一屏刷完三个 App」的卖点。
2. **加两个 A 级当「内容广度」的证据**：掘金（技术，跟你身份强相关）+ 知乎日报（大众话题，卡片好看）。合计不到两小时，`adapters/simple_adapters.py` 里已经写好了。
3. **V2EX 只在有代理时开**：本机直连不通，必须走 `127.0.0.1:7890`；演示机没代理就会红一个 chip，不如不放首页。
4. **话术要分清两类源**：三个平台是「社交/内容平台的个性化流」，掘金/知乎日报是「资讯源」。被评委问「这不就是 RSS 吗」，答「RSS 是订阅，我们做的是把平台推荐流和个人关注流合成一条时间线，并且跨平台去重」。
5. **快手/微博/知乎关注流写进 roadmap**，不写进 V1。理由：机制和抖音重复，边际信息量低。

## 已落地代码

```
adapters/
├── models.py            Item / Comment 统一模型（id 带平台前缀）
├── base.py              Adapter 协议：start / pull / comments / close
├── cli_adapters.py      BiliCliAdapter（含封面补全）、XhsCliAdapter（登录门控）
├── douyin_browser.py    DouyinBrowserAdapter（浏览器回放 + 评论）
├── simple_adapters.py   JuejinAdapter / V2exAdapter / ZhihuDailyAdapter（HTTP + 代理兜底）
└── __init__.py          REGISTRY：bili / xhs / douyin / juejin / v2ex / zhihu
pull_all.py      本地试跑：python pull_all.py douyin bili juejin
```

实测输出（`pull_all.py`，2026-11-13）：

```
[bili  ] 11-12 20:10 ♥   364 💬 309 | 炉石geyuan6  | 从酒馆到明日方舟，急速入坑攻略
[douyin] 11-13 06:40 ♥ 10278 💬 181 | 李飞雪_      | 说出什么就会让什么永久消失
[juejin] 11-13 20:41 ♥    67 💬  56 | XCaptain     | 永别了，程序员！
[v2ex  ] 11-13 10:55 ♥     0 💬  97 | cpsony       | 同事老婆昨天被诈骗了 2W+，分享下骗局
[zhihu ] --          ♥     0 💬   0 |              | 古代没有电灯，晚上过了8点，古人都怎么打发时间？
```
---

# 第二轮：开放平台普查（2026-11-13 22:20–22:35）

> 问题：还有哪些**常见的、比较开放的**社交/内容平台适合接？
> 方法：37 个端点逐个打点（直连 → 代理兜底），记状态码/体积/字段；脚本在 `probes/probe_platforms_survey.py`、`probe_platforms_survey2.py`、`probe_field_richness.py`。

## 先修正上一轮的两个结论

| 上轮结论 | 实测 | 修正 |
|---|---|---|
| 知乎热榜 API 要登录 | `api/v3/feed/topstory/hot-list-web?limit=20&desktop=true` → **200 / 30KB / 20 条** | 换端点即可，免登录 |
| 36 氪 RSS 已废弃 | RSS 确实返回 HTML，但 `POST gateway.36kr.com/api/mis/nav/home/nav/rank/hot` → **200 / 28KB / 50 条** | 接口活着，只是 RSS 死了 |

## A. 真正「开放」：官方 API、有文档、能拿你自己的流

| 平台 | 开放协议 / 接口 | 实测 | 拿个人流要什么 | 判断 |
|---|---|---|---|---|
| **Bluesky** | AT Protocol，`public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed` | 200 / 24KB，免登录可读任意公开账号 | app password（几行代码换代币），`getTimeline` 即个人关注流 | 最干净的「开放社交」样本，接入约 1 小时 |
| **Mastodon** | `/api/v1/timelines/home` | 公共时间线现在**必须登录**（422 requires an authenticated user）；`POST /api/v1/apps` 应用注册 **200**（返回 client_id/secret） | 用户在自己实例授权一次 | 协议开放，但要走过 OAuth，演示流程长 |
| **V2EX** | API v2 `api/v2/nodes/...` | **401 Token not found** | Personal Access Token（个人设置页自助申请） | 有 token 就能拿关注/通知；无 token 只能热帖 |
| **YouTube** | Data API v3 / 频道 RSS | RSS 200（27KB）；Data API 无 key 时 403 Method doesn't allow unregistered callers | OAuth 授权订阅列表；或只订频道 RSS | 需代理，国内场景弱 |
| **Reddit** | .json / OAuth | 直连与代理均 **403**（返回 Blocked 页） | 即便有 token 也受网络限制 | 放弃 |

**结论**：真正「开放 + 能拿个人流 + 国内可直连」的只有 Bluesky；Mastodon 次之（协议开放但要 OAuth 跳转）。
它们对演示的价值是「故事」，对用户的价值接近零（我们不在上面）。

## B. 免登录公开流，能立刻接（第二轮新发现）

| 平台 | 接口 | 实测 | 字段 | 成本 |
|---|---|---|---|---|
| **知乎热榜** | `GET zhihu.com/api/v3/feed/topstory/hot-list-web` | 200 / 30KB / 20 条 | 标题、摘要、封面、问题链接、「442 万热度」 | ~35 行 |
| **头条热榜** | `GET toutiao.com/hot-event/hot-board/?origin=toutiao_pc` | 200 / 120KB / 50 条 | 标题、HotValue、封面、跳转 URL | ~35 行 |
| **36 氪热榜** | `POST gateway.36kr.com/.../rank/hot` | 200 / 28KB / 50 条 | 标题、作者、封面、阅读/点赞/收藏数 | ~40 行 |
| **B 站热门** | `GET api.bilibili.com/x/web-interface/popular` | 200 / 16KB / 100 条 | 标题、UP 主、播放、封面、时长 | ~30 行 |
| **什么值得买** | `post.smzdm.com/feed/` | 200 / 45KB，标准 RSS | 标题、链接、摘要、图 | ~20 行（RSS 通用） |
| **快手热榜** | `POST kuaishou.com/graphql`（visionHotRank） | 200 / 5KB / 49 条，**无需签名** | 只有词条名，hotValue 为 null | 不建议（拼不出卡片） |

## C. 要登录 cookie 才拿得到「自己的流」（未验证到底）

| 平台 | 实测无 cookie | 判断 |
|---|---|---|
| 微博 | `m.weibo.cn` container API **432**、`weibo.com/ajax/side/hotSearch` **403** | 带 cookie 大概率能通（纯 JSON 无签名），但风控严、易掉线 |
| 知乎关注流 | 热榜可用，关注流需 `x-zse-96` 签名 | 投入等同抖音，不划算 |
| 豆瓣 | 电影新片 `j/new_search_subjects` 200 可用；广播/关注流需登录 | 只有「公开榜单」，没有个人化流 |
| 雪球 | 热帖接口被 WAF 拦（返回 renderData 验证页） | 放弃 |
| 贴吧 | 热榜 topicList 200（44KB，真数据） | 可用但内容质量差 |
| 虎扑 | 步行街 HTML 200，无内嵌 JSON | 要写 HTML 解析，性价比低 |

## D. 明确不可用（本轮复核）

| 平台 | 实测 |
|---|---|
| 小红书 homefeed（纯 HTTP 直连） | 406（code -1），需 `x-s` 签名；**改用 `ctx.browser.capture` 截页面自己发的请求后可用**（见 B 级表） |
| 抖音热榜（免签） | 200 但 **0 字节** — 仍需 a_bogus |
| 今日头条 feed | 200 但 **0 字节** — 反爬 |
| CSDN 首页推荐 | 404 |
| InfoQ 列表 | 451（地域/风控拦截） |
| 微信公众号 | 无公开接口 |

## 第二轮建议

1. **加一栏「热榜」**，不混进主时间线：知乎热榜 + 头条热榜 + 36 氪热榜，三个共约 110 行，免登录、零风控。
   好处：chip 从 4 个变 7 个，演示时「一屏看全平台」的观感立起来，而且**不依赖扫码**（扫码失败也不影响）。
2. **Bluesky 当「开放协议」故事**，进 roadmap 不进 V1：接入 1 小时，讲「连国际开放社交协议都能接」很加分，但用户自己不刷，演示时最多占 5 秒。
3. **微博 / 知乎关注流 / 快手**继续不做：机制与抖音重复，且都有风控。
4. **Mastodon / YouTube / Reddit** 直接排除：要 OAuth 跳转或需要代理，现场演示是定时炸弹。
---

# 第三轮：国内平台的「登录态个性化流」能不能拿（2026-11-14 15:40）

> 问题：国内哪些平台能拿到**登录后**的、**平台自己推给用户**的信息流（不是搜索、不是热榜）。
> 方法：`probes/probe_login_feeds.py`、`probe_login_feeds2.py` 逐个打点；判据是状态码 + 错误体，能区分「只差 cookie」和「还差签名」。

## 一个前提事实

**国内没有一家平台把「推荐流 / 关注流」开放给个人开发者。**
B 站开放平台只放开投稿与直播；抖音开放平台只有分享与授权登录；小红书开放平台是电商与蒲公英；微博开放平台对个人基本关闭。
所以「像官方 App 那样推送」这件事，国内平台全部只能靠逆向（cookie / 签名 / 浏览器回放），没有合规的官方路线。

## 分级：拿到它要付什么代价

| 级别 | 平台 | 实测证据 | 实现方式 | 成本 |
|---|---|---|---|---|
| **已跑通** | B 站 | `bili feed recommend` / `feed timeline` 在本机已登录态可用 | CLI 复用 cookie | 0（已完成） |
| **已跑通** | 抖音 | 浏览器回放 `/aweme/v2/web/module/feed/`，未登录即出 20 条 | Playwright + 持久化登录目录 | 0（已完成） |
| **已跑通** | 小红书 | 已登录（cookie 含 `id_token`），`explore` 页 `homefeed` 截到 29 条 | 浏览器截接口 + 宿主注入 cookie | 0（已完成） |
| **只差 cookie** | B 站动态 | `x/polymer/web-dynamic/...` 返回 `{"code":-101,"message":"账号未登录"}` | 同 B 站，cookie 即可 | ~30 行 |
| **只差 cookie（风控中）** | 微博 | 移动端推荐流 **432**、关注流 **432**、web 端 **403** | cookie + 设备参数，纯 JSON 无签名 | ~150 行 + 调试风控 |
| **只差 cookie** | 网易云音乐动态 | `api/event/get` 返回 `{"code":301}`（需登录） | cookie | ~40 行 |
| **只差 cookie** | 贴吧 | 关注流 403（需 BDUSS） | cookie + 表单参数 | ~120 行 |
| **要签名** | 知乎 | 推荐流 / 关注流均 `401 AuthenticationError`，需 `x-zse-96` | 浏览器回放（同抖音） | ~1 天 |
| **要签名** | 快手 | web 端 feed 走签名 graphql（热榜反而免签） | 浏览器回放 + 单独调登录 | ~1 天 |
| **不可行** | 微信（公众号/视频号/朋友圈） | 无任何公开接口 | — | — |
| **不可行** | 即刻 | `web-api.okjike.com/api/general/feed` **404**（旧 token 接口已下线） | — | — |
| **不可行** | 豆瓣 | `j/feed/recommend` **404**，广播无公开接口 | — | — |
| **不可行** | 雪球 | 热帖接口被 WAF 拦（renderData 验证页） | — | — |

## 结论

1. 我们已经拿到的三个（B 站 / 抖音 / 小红书）就是国内「登录态 + 平台推荐流」能拿到的**上限组合**，不是随手挑的。
2. 想再加一个真·社交流：**微博**性价比最高（纯 JSON、无签名、内容量大），代价是风控调试；风险点在演示当天关键词被限流。
3. 想再加一个「你的内容」：**B 站动态**几乎白送（cookie 已存在，30 行），但信息量与主 feed 高度重叠。
4. 知乎 / 快手要走浏览器回放，与抖音同构，边际信息量低，不建议在黑客松周期内做。
