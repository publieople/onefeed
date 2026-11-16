# 005 详情页：视频 / 图文在本地看完

状态：草案 v0.1（2026-11-16）
前置：004 之后（插件市场、评论能力、卡片体系已上线）
目标读者：宿主/前端/插件三侧开发者

## 1. 背景与目标

现在卡片点开只会弹出右滑抽屉，抽屉能看标题、封面、正文摘要和评论，但**视频播不了、图文只能看一张封面**，想真正看完还得点「去 B 站看原帖」跳出去。用户诉求很直接：

> 现在还有视频和图文的详情页要实现，不能让用户每次都点进原视频平台去看。

所以 005 要解决的是**阅读/观看闭环**：在 OneFeed 自己的页面上，把一条内容能看的部分看完。

三条硬约束（都来自已有的风险边界，不改）：

1. **只读**：不下载、不转存、不搬运。媒体字节只在播放/浏览时流经宿主，不落盘、不进缓存。
2. **不逆签名**：能用官方 iframe 的就用 iframe；不能用 iframe 的，靠浏览器回放页面自己发出的已签名请求，不自己算 a_bogus / x-s。
3. **凭证不出宿主**：插件拿不到 cookie 明文，边车代理所需的 Referer / Cookie 由宿主按域名白名单注入。

不在 005 范围内：搜索、离线收藏、下载、转码、弹幕、倍速之外的高级播放器功能、评论区二级展开（已有）。

## 2. 现状盘点（写方案前确认过的事实）

| 位置 | 现状 | 对 005 的影响 |
| --- | --- | --- |
| `onefeed/web/src/App.tsx:114-118` | 已用 react-router，三条路由 / /market /settings | 详情页直接加一条路由，不引新依赖 |
| `onefeed/web/src/pages/FeedPage.tsx:135` | `<Card onOpen={setDrawer} />`，点卡片开抽屉 | 改成 `navigate(\`/item/\${id}\`)` |
| `onefeed/web/src/components/Drawer.tsx`（313 行） | 标题/封面/正文/标签/同题兄弟/评论/去原帖 | 95% 内容可搬进详情页；迁移完成后抽屉下线 |
| `onefeed/api.py:163-191` | GET /api/item/{id} 返回 item + siblings + reasons | 详情页直接复用，不必新开接口 |
| `onefeed/api.py:194-228` | GET /api/item/{id}/comments，插件没实现时返回 reason | 详情页复用；已有缓存 10 分钟 |
| `onefeed/plugin_runtime/host.py` | `DEFAULT_TIMEOUTS` 里已预留 `"detail": 92.0`，但没有 `detail()` 方法 | 005 把这个占位补实 |
| `onefeed/plugin_runtime/manifest.py` | `FEATURES = {"comments"}` | 加 `"detail"` 与 `"media"` 两项 |
| `onefeed/onefeed/store.py` | 三张表 items / runs / plugins，SCHEMA_VERSION = 2 | 加第四张表 details（不塞进 items，避免主表膨胀） |

## 3. 能力设计

### 3.1 manifest 新增声明

```jsonc
{
  "features": ["comments", "detail"],   // 有 detail 才拉详情，没有就只出卡片
  "mediaHosts": ["*.hdslb.com", "*.douyin.com", "*.douyinvod.com", "*.xhscdn.com"],
  "embeds": ["bilibili"]                // 可选：声明该平台可整页 iframe 嵌入
}
```

`mediaHosts` 是**边车代理的凭证白名单**：只有目标域名命中这里，宿主才会注入 Referer / Cookie。插件不声明就一律不注入，避免插件把宿主的 cookie 引到第三方域名上。

### 3.2 插件新方法 `detail(ctx, args)`

`args = { item }`（宿主传回完整 item，含 `extra`），返回值统一为：

```jsonc
{
  "body": {                      // 可选：正文
    "kind": "html" | "markdown" | "text",
    "value": "…"
  },
  "media": {                     // 可选：视频
    "type": "embed" | "file",
    "embedUrl": "https://player.bilibili.com/player.html?bvid=…",  // type=embed 时必填
    "url": "https://…mp4",       // type=file 时必填，宿主会改写成边车地址
    "poster": "https://…jpg",
    "duration": 710,
    "referer": "https://www.douyin.com/",   // 宿主只在 mediaHosts 命中时使用
    "expiresAt": 1799999999                  // 直链会过期时必须给，宿主据此重取
  },
  "images": ["https://…jpg"],    // 图文：按顺序，第一张通常等于封面
  "stats": { "view": 0, "like": 0, "comment": 0 },   // 可选，覆盖列表页拿到的数
  "note": ""                     // 可选：给用户的一句说明，例如「这条只有标题，正文要点原帖看」
}
```

约定：

- 插件**不返回本地文件路径**，只返回远端 URL 或 embed URL。
- 插件**不返回 cookie**，也不自己拼代理地址；`url` 给的是原始直链。
- 返回空对象 `{}` 合法，表示「这个平台只能看卡片」，宿主退回卡片态。
- 抛错则宿主记录 error，前端显示「详情暂时取不到，去原帖看」+ 原因。

### 3.3 宿主新接口

**GET /api/item/{item_id}/detail?refresh=false**

- 命中 `details` 表且未过期 → 直接返回，带 `from_cache: true`。
- 未命中 → `host.detail(plugin_id, item)`，落库后返回。
- 插件未声明 `detail` → `{"supported": false, "reason": "<插件> 的插件没有提供详情接口"}`（和评论同款口径，不再写多余解释）。
- 失败 → `{"supported": true, "error": "…"}`，不抛 500。

返回体裁对齐评论接口：`{supported, detail: {...}, from_cache, item?}`。

**GET /api/media/{item_id}/{slot}**

边车（sidecar）代理，`slot` ∈ `video` | `poster` | `img-0`、`img-1`……

- 服务端从 `details` 表里取该 slot 对应的**原始 URL**，客户端传不了任意地址 → 天然防 SSRF、防被当成开放代理。
- 注入 `Referer` / `User-Agent` /（平台专属）`Cookie`，仅当目标 host 命中该插件的 `mediaHosts`。
- 透传 `Range` 请求头与 `206` / `Content-Range` 响应，边看边播，不落盘。
- 响应头加 `Cache-Control: private, max-age=0`，不做磁盘缓存；内存里也不留整段 body。
- 非 2xx/206 原样回传状态码，前端据此提示「直链过期，点刷新重取」。

### 3.4 详情缓存表

```sql
CREATE TABLE IF NOT EXISTS details (
    item_id    TEXT PRIMARY KEY,
    supported  INTEGER NOT NULL DEFAULT 0,
    body_kind  TEXT NOT NULL DEFAULT '',
    body       TEXT NOT NULL DEFAULT '',
    media      TEXT NOT NULL DEFAULT '{}',   -- JSON：type/url/embedUrl/poster/duration/expiresAt
    images     TEXT NOT NULL DEFAULT '[]',
    stats      TEXT NOT NULL DEFAULT '{}',
    note       TEXT NOT NULL DEFAULT '',
    error      TEXT NOT NULL DEFAULT '',
    fetched_at INTEGER NOT NULL DEFAULT 0,
    expires_at INTEGER NOT NULL DEFAULT 0
);
```

TTL：默认 6 小时；插件给了 `media.expiresAt` 时取两者较小值。刷新信息流时**不清**详情缓存（详情比列表稳定），只有 `refresh=true` 或过期才重取。

### 3.5 前端页面 `/item/:id`

布局（桌面，1180 内容宽）：

```
┌──────────────────────────────────────────────┬────────────────┐
│ ← 返回    平台 chip · kind 标签 · 时间        │  同题其他平台   │
│ 标题（可选中复制）                            │  （有 cluster） │
│ 作者 · 头像 · 发布时间 · 统计块               │                │
│ ┌────────────────────── 媒体区 ────────────┐ │                │
│ │ video: iframe / <video>                  │ │                │
│ │ images: 大图 + 缩略条（点开灯箱）          │ │                │
│ │ article/short: 正文（富文本 / 纯文本）     │ │                │
│ │ list: 摘要卡 + 「去原平台看」              │ │                │
│ └──────────────────────────────────────────┘ │                │
│ 标签                                          │                │
│ 评论（复用现有评论组件，可展开楼中楼）          │                │
│ ─ 去 B 站看原帖 · 复制链接（常驻，不藏）        │                │
└──────────────────────────────────────────────┴────────────────┘
```

渲染规则（按 kind）：

| kind | 主区渲染 | 降级顺序 |
| --- | --- | --- |
| video | `media.type=embed` → iframe（16:9，`allowfullscreen`）；`type=file` → `<video>` 指向边车地址 | embed → file → 封面 + 去原帖 |
| images | 第一张大图 + 下方网格；点击进灯箱（左右键切换）；图片走边车 | 原图 → 封面 → 纯文字 |
| article / short | `body.kind=html` → DOMPurify 白名单净化后渲染（保留 h1-h4/p/ul/ol/li/pre/code/blockquote/img/a/table）；markdown → 渲染器；text → `white-space: pre-wrap` | html → markdown → text → 列表里的 text 摘要 |
| list | 大号标题 + 热度/名次 + 一句摘要 + 去原帖按钮（热榜条目本来就没有正文，不做假正文） | — |

详情页正文里的 `<img>` 也要经过边车改写，否则掘金/小红书会 403。

交互细节：

- 打开时先渲染**已有的 item 数据**（标题/封面/统计），详情异步补进来，避免整页空白。
- 详情加载中：媒体区显示 skeleton + 「正在取详情」；加载失败：一行灰字 + 「重试」+「去原帖」。
- 卡片点击从「开抽屉」改为「进详情页」；抽屉在 T43 之后删除，其评论/同题逻辑搬进页面。
- 保留 `?peek=1` 兼容旧链接（直接重定向到页面）。

## 4. 六平台可行性（本地实测证据，2026-11-16）

| 平台 | 详情正文 | 视频 | 结论 | 证据 |
| --- | --- | --- | --- | --- |
| **B 站** | `bili video info <BV> --raw` 拿简介、分区、统计 | **官方 iframe**：`player.bilibili.com/player.html?bvid=…` 在第三方页面可正常播放 | ✅ 最省事，P1 就做 | 真实 Chromium 打开 data: 页面嵌入 iframe，11:50 视频正常渲染出播放器与封面（截图已存） |
| **V2EX** | 官方 API `/api/topics/show.json?id=` → `content` 纯文本 995 字 + `content_rendered` HTML 1090 字 | 无视频 | ✅ P1 | HTTP 200，字段齐全；`replies` 是计数(78)不是数组，回复另取或不展示 |
| **掘金** | 文章页 SSR 直出 `<article>`：24KB HTML / 13KB 正文 | 无 | ✅ P1（直连 HTML + 净化） | `GET juejin.cn/post/7707927071724486665` → 200 / 131 030 字符，含 mark_content、`<article>`；注意 `content_api/v1/article/detail` 三个参数形态全失败（参数错误 / 内容为空 / 路由不存在），别走 API |
| **小红书** | 详情接口需 x-s/x-t 签名，带 cookie + xsec_token 直连 **406** | 笔记页自己会请求 `/api/sns/web/v1/feed`（已签名），返回 `video.media.stream.h264[0].master_url` | ⚠️ P3：`ctx.browser.capture` 抓笔记页那条响应；媒体走边车 | 直连 406 Not Acceptable；现有插件已用同样思路抓 homefeed |
| **抖音** | 详情接口要 a_bogus；但列表 JSON 里本来就有 `video.play_addr.url_list` | 直链带签名、有效期短，必须带 Referer 走边车 | ⚠️ P3：P2 先在 pull 时把 `play_addr` 存进 `extra.play_url`，P3 再补 detail 兜底重取 | 插件现有 `awemeItem()` 已经解析 video 对象，只是把 play_addr 丢了 |
| **知乎热榜** | 榜单条目只有标题 + 热度，没有正文 | 无 | ⛔ 不做详情，只做摘要卡 + 跳转 | 现有 item 的 text 为空，`kind=list` |

## 5. 风险与边界

| 风险 | 处理 |
| --- | --- |
| 边车变成开放代理 | 只接受 `{item_id, slot}`，URL 由服务端查表得出；不读客户端传的 url |
| 凭证外泄 | 只有 host 命中插件 `mediaHosts` 才注入 Cookie；跳转/重定向到非白名单 host 时丢弃凭证 |
| 直链过期（抖音/小红书） | 存 `expiresAt`，过期或 403 时自动重取一次；仍失败则显示「去原帖」 |
| 大文件拖垮宿主 | 流式转发、不落盘、单条并发上限 4、单请求超过 30 分钟断开 |
| 富文本 XSS | 服务端只做长度截断；前端 DOMPurify 白名单净化，禁 script/style/iframe/on* 属性 |
| 平台改版 | detail 是插件方法，改版只改一个插件，不动宿主；失败降级到卡片 + 跳转 |
| 「本地看完」被理解成盗播 | README 与设置页明确：只读、不下载、不转存；B 站用官方播放器，播放量归原平台 |

## 6. 验收标准

- AC-D1：B 站视频详情页能在 OneFeed 页面内直接播放，不跳转外站。
- AC-D2：V2EX 帖子详情页显示完整正文（≥ 样本 995 字的 95%），评论区正常。
- AC-D3：掘金文章详情页显示净化后的正文，图片正常显示（走边车），无脚本执行。
- AC-D4：小红书图文详情页显示多图，可左右切换；视频笔记能播（P3 达成）。
- AC-D5：抖音视频能播（P3 达成）；拿不到直链时显示「去原帖」而不是空白播放器。
- AC-D6：插件未声明 detail 的平台（如知乎热榜）显示「<插件> 的插件没有提供详情接口」，不留空白、不写好几句解释。
- AC-D7：任意详情页在断网/直链过期时都能优雅降级，页面不白屏，始终有「去原帖」出口。
- AC-D8：`/api/media` 对非白名单域名不注入 Cookie（用假 item 验证）。

## 7. 分三批实施

| 批次 | 内容 | 预估 |
| --- | --- | --- |
| P1（今晚到明天） | details 表 + host.detail + /detail 接口 + /media 边车（仅 B 站/V2EX/掘金）+ 详情页骨架（video iframe / article / text）+ 卡片跳转 | 6–8 h |
| P2 | 图文画廊 + 灯箱 + 图片边车 + DOMPurify + 抖音 play_addr 入 extra + 知乎 list 摘要卡 | 3–4 h |
| P3 | 小红书笔记页回放、抖音 detail 兜底重取、过期自动刷新、抽屉下线 | 4–5 h |

## 8. 与 003/004 的关系

- 003 定义卡片与抽屉；005 把「看内容」从抽屉升级成页面，抽屉逻辑回收。
- 004 定义插件市场与评论能力；005 复用同一套 `features` 声明式能力，不引入新的插件生命周期。
- 插件版本号：加了 detail 的插件 minor +1（bilibili 0.2.0 → 0.3.0 等），宿主 `HOST_VERSION` 升到 0.3.0，`minHostVersion` 同步。
## 9. 嵌入可行性实测（2026-11-16）

详情页最终能不能「把原站网页塞进 iframe」，2026-11-16 在真实 Chrome（1280×800，非 headless）与 Playwright 两套环境里各测了一遍。结论是只有 B 站能嵌，其余三家都不行，所以详情页必须自己渲染，不能指望 iframe。

| 平台 | 服务端头 | 浏览器里实际表现 | 结论 |
| --- | --- | --- | --- |
| B 站 | `player.bilibili.com/player.html` 200，无 XFO、无 CSP | 播放器正常渲染，可播 | 唯一可嵌，官方播放器 |
| 抖音 | `www.douyin.com/video/<id>` 200 但 CSP `frame-ancestors` 只放行 `*.douyin.com` 等字节域名；`iesdouyin.com/share`、`m.douyin.com/share` 均 302 回 `www.douyin.com`，带 `X-Frame-Options: SAMEORIGIN` | iframe 内是灰色空块 + 破图标，控制台报 `Framing ... violates the following Content Security Policy directive: "frame-ancestors ..."` | 任何登录态都嵌不了 |
| 小红书 | `/explore/<id>` 无 XFO、无 CSP（裸请求 302 到 /login） | 真实 Chrome 里被风控拦成「安全限制 当前网络存在风险，请切换可靠网络后重试 300012」；Playwright 注入 cookie 后能渲染笔记但登录态为空、盖登录弹窗 | 不可靠，且跨站 iframe 带不上 Lax cookie，等于永远匿名 |
| 知乎 | question 页无 XFO、无 CSP | 顶层与 iframe 都返回 WAF 的 `{"code":40362,"message":"您当前请求存在异常..."}` | 匿名直接封；登录后能否读需在宿主登录窗口里实测 |

截图留档：`design/embed-real-xhs-300012.png`、`design/embed-real-douyin-blocked.png`、`design/embed-real-zhihu-bili.png`（知乎 40362 + B 站播放器同屏）、`design/embed-real-zhihu-top-waf.png`、`design/detail-bili-embed.png`。复现脚本 `probes/probe_embed_matrix.py`、`probes/probe_frame_headers.py`、静态对照页 `probes/embed_probe.html`。

对设计的两个硬约束：

1. `media.type="embed"` 只留给 B 站。小红书、抖音、知乎的详情正文由插件给出 `{body}`，媒体走 `type="file"` 直链或只显示封面 + 「去原帖」，别在 iframe 里赌能不能出内容。
2. 知乎要接进来，先加 `auth.py:SPECS` 一条登录窗口（`url=https://www.zhihu.com/`、`domain=.zhihu.com`、判据 cookie `z_c0`），用宿主登录窗口拿到 `z_c0` 再回放 question 页；登录态下才谈得上 `ctx.http` 读页面或 `ctx.browser` 截取。推荐流另有 `x-zse-96` 签名门槛，纯 http 那条路走不通。

## 10. 补充：不靠 iframe 的四条嵌入路线（2026-11-16 实测）

§9 只证明了「原站网页塞进 iframe」不通，不等于详情页做不出来。完整路线、别人项目里的先例、每条的实测数据写在 [`embedding-routes.md`](./embedding-routes.md)，这里只记对 spec 有改动的三条：

1. **抖音有官方可嵌播放器**：`https://open.douyin.com/player/video?vid=<aweme_id>`，响应 200、无 XFO/CSP；第三方页面里点播放实测 `currentTime=7.73s`、`readyState=4`。所以 §9 的「抖音只能显示封面 + 去原帖」作废，`media.type="embed"` 对抖音同样适用（`vid` 必须是数字 aweme_id，传 `play_addr.uri` 会显示"加载失败"）。
2. **小红书不需要边车**：回放 `window.__INITIAL_STATE__.note.noteDetailMap` 能拿到标题、正文、图集、`media.stream` 视频流；媒体直链（`xhscdn.com`，带 `sign`+`t`）**无 Referer 也返回 206**，前端可直接 `<video>/<img>`。
3. **知乎按内容判定，不看状态码**：回放 question 页时 HTTP 是 403，但 `js-initialData.initialState.entities` 完整（question 带 `answerCount=241`、3 条 answer 含作者/赞数/正文）。判定条件写成「有 `js-initialData` 就算成功」。

抖音直链（`douyinvod.com`）仍是唯一需要 `/api/media` 注入 `Referer: https://www.douyin.com/` 的：无 Referer 403，带 Referer 206 `video/mp4`。边车因此保留，作为「官方播放器拿不到 aweme_id」时的兜底。

新增能力（P2）：`ctx.browser.evaluate` 只接受宿主内置的**具名提取器**（`xhs.note` / `zhihu.question`），不接受插件传任意 JS。


