# 嵌入路线：别人怎么做的，我们实测能走哪条

状态：实测记录（2026-11-16）
关联：`specs/005-detail/spec.md` §9 只回答了「直接 iframe 能不能嵌」，本文回答「那还有什么办法」。

## 0. 一句话

直接 iframe 嵌站内页（除 B 站）确实不通，但「把自己应用里的内容看完」有四种已被别人验证过的做法，我们逐条实测，四条里有三条当场跑通。

## 1. 参考实现（都是别人踩过的路）

| 项目 | 做法 | 对我们的意义 |
| --- | --- | --- |
| [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) | Playwright 登录保活，**在页面上下文里执行 JS 表达式取签名参数**，"无需 JS 逆向" | 小红书/知乎的正解：签名交给页面自己算，我们只要 JSON |
| [DIYgod/RSSHub · douyin](https://github.com/DIYgod/RSSHub/blob/master/lib/routes/douyin/namespace.ts) | 官方文档直言"抖音的 CDN 会验证 Referer"，给三种变通：内嵌视频走 `multimedia_hotlink_template` / `wrap_multimedia_in_iframe`、点"视频直链"、或回原帖 | 我们测到的 403 不是我们写错，是平台设计 |
| [Evil0ctal/Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) | 自托管 API，直接给无水印直链（选平台已发布的干净流，不做去水印处理） | 直链可拿，但播放仍受 Referer 约束 |
| [ferdium/ferdium-app](https://github.com/ferdium/ferdium-app) | Electron 里每个服务一个 `<webview>`，整站嵌进来 | 桌面端可行，web 宿主不可用（跨域 + 风控） |
| [niutech/x-frame-bypass](https://github.com/niutech/x-frame-bypass) / [Iframe-Proxy](https://github.com/Nikhiljain180/Iframe-Proxy---CSP-bypass-solution) | 前者用组件 + CORS 代理绕 XFO，后者 Node 后端扒掉 `X-Frame-Options` / CSP | **对我们无效**，原因见 §3 |

## 2. 四条路线，逐条实测

### 路线 A：官方播放器 iframe（抖音有，B 站有）

抖音开放平台提供了对外播放器，参数是 **数字 aweme_id**，不是 `play_addr.uri`：

```
https://open.douyin.com/player/video?vid=7677413413173169449&autoplay=0
```

实测（真实 Chrome，第三方页面 127.0.0.1:8793 里嵌 iframe）：

| 检查项 | 结果 |
| --- | --- |
| HTTP | 200，`text/html`，**无 X-Frame-Options、无 CSP** |
| 渲染 | 封面 + `抖音` 标识 + 作者 `@子轩轩要谦虚` + 时长 04:46 + 2.7w 赞 + 播放按钮 |
| 点播放 | `currentTime=7.73s`，`paused=false`，`readyState=4`，无 error —— **真的在播** |
| 反例 | 同一个播放器传 `vid=play_addr.uri`（`v0200fg10000...`）→ 画面显示"加载失败，你可以点此刷新" |

截图：`design/embed-douyin-official-player.png`（左=uri 版失败，中=aweme_id 版正常，右=B 站对照）、`design/embed-douyin-player-playing.png`（播放中）。

B 站继续用 `player.bilibili.com/player.html?bvid=...`，200、无 XFO/CSP、可播（`design/embed-real-zhihu-bili.png`）。

### 路线 B：浏览器回放，把页内 JSON read 出来（小红书 / 知乎）

宿主已有的 `ctx.browser.capture` 是「持久上下文 + 注入 cookie + 按正则截响应」。实测它能拿到抖音详情，但小红书的笔记数据**不在 XHR 里**，在页面的 `window.__INITIAL_STATE__`，而且那个对象里有 `new Map([])` 这种非 JSON 字面量，**服务端拿到的 HTML 没法直接 json.loads**。必须让页面自己把它序列化出来：

```js
// 在页面上下文执行，返回可 JSON 化的结构
const s = window.__INITIAL_STATE__ || {};
const m = s.note && s.note.noteDetailMap;
const out = [];
m.forEach((v, k) => out.push({ key: k, note: v.note }));
return { notes: out };
```

实测结果（笔记 `6aeac597000000000e0340ac`，注入宿主已登录的 11 个 cookie）：

| 字段 | 值 |
| --- | --- |
| title | Claude写的字里藏着水印，能洗掉吗？ |
| desc | 完整正文（含话题标签），约 200 字 |
| type | video |
| 图集 | 1 张，`imageList[0]` 有 `url` / `urlPre` / `stream` |
| 视频流 | `media.stream` 的 key 是 `EF7/EF4/EF6/EF5`（不是 h264），`masterUrl` 指向 `sns-video-v6.xhscdn.com` |
| 作者 | 慢不下来的 Abreto |
| 互动 | 赞 368 / 评 41 / 藏 292 / 转 101 |
| 时间地点 | 1793770903000（ms）、上海 |

**关键差异**：小红书媒体直链**不需要 Referer**，带 `sign` + `t`（过期时间）即可：

| 资源 | 无 Referer | 带 Referer |
| --- | --- | --- |
| 视频 `sns-video-v6.xhscdn.com/...mp4` | 206 `video/mp4` | 206 `video/mp4` |
| 图片 `sns-webpic-qc.xhscdn.com/...` | 206 `image/webp` | 206 |

也就是说小红书只要拿到 JSON，前端直接 `<video src>` / `<img src>` 就能播能看，**不需要边车代理**（只要在 `t` 过期前用）。

知乎同样走回放。实测 `https://www.zhihu.com/question/2104528020287354223`：

| 检查项 | 结果 |
| --- | --- |
| 导航 status | **403**（但内容完整返回，title 正确，HTML 240KB，无 WAF `40362` 标记） |
| 数据位置 | `<script id="js-initialData">` → `initialState.entities` |
| 拿到什么 | question：标题、`answerCount=241`、`detail` 608 字；answers：3 条，含作者、赞数（5650 / 883）、正文 HTML |

**教训**：知乎的 403 是状态码，不是内容缺失。判定必须看有没有 `js-initialData`，不能看 status。

### 路线 C：回放拿直链 + 宿主边车补 Referer（抖音兜底）

抖音 `aweme/v1/web/aweme/detail` 回放（未登录也能拿）：

- desc：`红蛋RM277-见面就秒杀！ #三角洲行动 ...`
- `play_addr.url_list`：3 条，落在 `v26-web.douyinvod.com` / `v11-weba.douyinvod.com`
- 封面：`p3-pc-sign.douyinpic.com`
- 互动：赞 26792 / 评 282

直链取用受 Referer 约束，实测：

| 请求头 | 结果 |
| --- | --- |
| 无 Referer | **403 Forbidden** |
| `Referer: https://www.douyin.com/` | **206 `video/mp4`** |
| `Referer: https://www.douyin.com/video/<id>` | 206 `video/mp4` |

所以抖音的直链播放必须有 `/api/media/{item}/{slot}` 边车注入 Referer（spec §4.3 已有设计），浏览器端 `<video>` 设 `referrerpolicy` 是没用的——发出的还是我们自己的域名。

### 路线 D：剥头代理（实测无效，写下来免得再试）

`x-frame-bypass` 和 `Iframe-Proxy` 解决的是**浏览器侧同源策略**：把 `X-Frame-Options` / `frame-ancestors` 删掉，浏览器就肯渲染了。但小红书拦住我们的不是浏览器：

- 小红书 iframe 里返回的是 **200 的 HTML 风控页**（"安全限制 / 当前网络存在风险 / 300012"），剥掉响应头，页面上还是那张风控页；
- 知乎是被 **WAF 判请求指纹**（`{"code":40362,"message":"您当前请求存在异常"}`），XFO 根本不是瓶颈；
- 抖音的 CSP `frame-ancestors` 的确能剥，但剥完拿到的页面自己会去要 `aweme/detail`（带签名），代理转发时没有 `a_bogus`，一样空。

结论：**这条路只在「目标站点只是不想被嵌、但内容对匿名请求开放」时成立**，我们这三个目标都不属于这一类。

## 3. 结论：我们该怎么做

| 平台 | 方案 | 依赖 | 风险 |
| --- | --- | --- | --- |
| B 站 | 官方 iframe player | 无 | 无（官方支持） |
| 抖音 | **官方 embed player**（`vid=aweme_id`），拿不到 aweme_id 时退回「回放直链 + 边车 Referer」 | aweme_id 从插件详情拿 | 低，官方播放器即开放接口 |
| 小红书 | 回放读页内 state → 自渲染图集/视频 | 新增 `browser.evaluate` 能力；媒体直链无 Referer 可播 | 中，登录态失效即不可用 |
| 知乎 | 回放读 `js-initialData` → 自渲染问答 | 同上；判定看内容不看 status | 中，WAF 可能整体 403 |

对 spec 的增量（P1 范围外，P2 加）：

1. `capabilities.py` 增加 `browser.evaluate`：只允许插件声明过的**具名提取器**（如 `xhs.note` / `zhihu.question`），表达式由宿主内置、不接受任意代码，返回值限 256KB。
2. 抖音插件详情返回 `embedUrl = https://open.douyin.com/player/video?vid=<aweme_id>`，宿主直接 iframe，不再要求边车。
3. 小红书/知乎插件返回 `{body, images, media.type="file"}`，媒体走 `/api/media`（小红书可直连，抖音必须代理）。

## 4. 复现命令

```powershell
cd onefeed
uv run python probes/probe_douyin_player.py        # 官方播放器 URL 与响应头
uv run python probes/probe_douyin_player_play.py   # 第三方 iframe 里点播放，看 currentTime
uv run python probes/probe_detail_via_browser.py   # 抖音 aweme/detail 回放
uv run python probes/probe_detail_urls.py          # 直链 Referer 对照 + 小红书媒体
uv run python probes/probe_xhs_evaluate.py         # 小红书页内 state 提取
uv run python probes/probe_zhihu_page.py           # 知乎 403 但内容完整
```
