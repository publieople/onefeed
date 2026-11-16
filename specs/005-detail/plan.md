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
