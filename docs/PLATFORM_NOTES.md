# 还能接哪些平台 —— 2026-11-13 实测记录

> 目的：回答「除了 B 站 / 小红书 / 抖音，还有哪些平台接起来便宜」。
> 所有结论都是本机当场跑出来的，不是看文档猜的。抓数时间 2026-11-13 20:40–20:55（Asia/Shanghai）。

## 一句话结论

**六个平台已经能跑**（B 站、抖音、掘金、V2EX、知乎日报、小红书待登录）。
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
| 小红书 | `xhs 0.1.4` | ⚠️ 未登录（`xhs feed --json` 报 `Not logged in. Run "xhs login" first.`） | 扫码后能拿探索页推荐流 |
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
