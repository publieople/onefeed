# OneFeed 插件架构（002-plugin-arch）

| 项 | 值 |
|---|---|
| 文档版本 | 0.1（提案，待评审） |
| 日期 | 2026-11-14 |
| 归属 | 替换 001 中 `adapters/` 的实现路径，产品需求不变 |
| 一句话 | 宿主不认识任何平台；平台适配是用户自己装的插件 |

---

## 1. 为什么要改成插件

**风险面**：仓库里躺着 B 站 / 抖音 / 小红书的抓取实现，"这个项目本身"就成了提供抓取工具的主体。平台风控、法务、商店审核的火力点全在主仓库。

**生态叙事**：插件化以后，产品是一个通用信息流客户端，平台能力由第三方（示例仓库、用户自己）提供。这跟落雪音乐的自定义源、MusicFree 的插件订阅是同一套结构：宿主只提供运行时和呈现，内容源与责任在插件侧。

**工程**：现在 `adapters/` 已经是三条技术路线（CLI 子进程 / Playwright 回放 / 纯 HTTP）。三条路线本来就是三种"能力"，抽象成插件能力后，再加平台就不改宿主代码。

### 与同类项目的对应关系

| 概念 | 落雪音乐 | MusicFree | OneFeed |
|---|---|---|---|
| 宿主 | 播放器 | 播放器 | 信息流客户端 |
| 插件 | 自定义源 `.js` | 插件 `.js` | 插件 `index.js`（CommonJS 风格，`module.exports`） |
| 分发 | 手动导入 / 链接 | 订阅链接 | registry 订阅 / 文件 / 粘贴 |
| 网络能力 | `lx.request` | 内置 `request` | `ctx.http` / `ctx.browser` / `ctx.cli` |
| 隔离 | 同进程 | 同进程 | QuickJS 沙箱 + 能力白名单 |

---

## 2. 三件东西

```
┌──────────────────────────────────────────────────────┐
│ Host（主仓库 onefeed）                                │
│  前端 React / FastAPI / SQLite / 去重 / 排序 / Agent  │
│  插件运行时（QuickJS）· 能力层 · 插件管理 UI          │
│  ⚠ 零平台实现：不认识 bilibili / douyin / xhs         │
└───────────────┬──────────────────────────────────────┘
                │ 加载 / 调用（能力白名单）
┌───────────────▼──────────────────────────────────────┐
│ Plugin（独立仓库 onefeed-plugins）                    │
│  bilibili · douyin · xiaohongshu · juejin · v2ex …   │
└───────────────┬──────────────────────────────────────┘
                │ 订阅
┌───────────────▼──────────────────────────────────────┐
│ Registry（registry.json，可托管在插件仓库 raw 地址）  │
└──────────────────────────────────────────────────────┘
```

---

## 3. 插件形态

一个插件 = 一个目录（可打包成单个 `.ofp`，本质是 zip）：

```
bilibili/
  plugin.json     # 清单：id / 版本 / 能力 / 声明式 feeds
  index.js        # 逻辑：实现 pull / detail / comments
  icon.svg        # 可选
```

宿主只认清单和 `module.exports` 上的几个方法。

---

## 4. Manifest 规范（`plugin.json`）

```json
{
  "schemaVersion": 1,
  "id": "bilibili",
  "name": "哔哩哔哩",
  "version": "1.0.0",
  "author": "onefeed-plugins",
  "description": "B 站推荐流与关注流（只读）",
  "license": "MIT",
  "minHostVersion": "0.2.0",
  "entry": "index.js",
  "icon": "icon.svg",
  "capabilities": ["http", "cli"],
  "kinds": ["video"],
  "feeds": [
    { "id": "recommend", "name": "推荐", "requiresAuth": true, "personalized": true },
    { "id": "following", "name": "关注", "requiresAuth": true, "personalized": true }
  ],
  "settings": [
    { "key": "cli_path", "type": "string", "label": "bili 可执行文件", "default": "bili" }
  ],
  "cli": { "allow": [["bili"]] }
}
```

| 字段 | 必填 | 说明 |
|---|---|---|
| `schemaVersion` | ✅ | 固定 `1`，宿主拒绝更高版本 |
| `id` | ✅ | 小写字母数字，全局唯一；决定 `Item.id` 前缀与数据目录 |
| `version` | ✅ | semver；升级只在用户确认后发生 |
| `minHostVersion` | ✅ | 低于此版本宿主拒绝装载并提示 |
| `capabilities` | ✅ | `http` / `browser` / `cli` 的子集，安装时逐条弹授权说明 |
| `kinds` | ✅ | 该插件会产出的卡片形态（见 §7），宿主据此预加载模板 |
| `feeds` | ✅ | 声明的流列表；运行时也可用 `feeds()` 动态返回 |
| `settings` | ❌ | 用户可改的参数（路径、语言），`secret: true` 的项加密存储、不回显 |
| `cli.allow` | 用 `cli` 时必填 | 允许的命令前缀白名单，宿主按前缀比对 `argv` |
| `homepage` / `license` | ❌ | 展示用 |

---

## 5. 生命周期

```
安装 → 校验（schema / 版本 / sha256）→ 授权页（逐条列能力）→ 启用
     → init(ctx) 一次
每次拉取：pull(ctx, {feedId, limit, cursor}) → 归一化 → 入库
点开卡片：detail(ctx, item) → comments(ctx, item, {limit})
登录：auth(ctx) 查状态 → login(ctx) 取二维码 → 宿主渲染 → 再 auth 确认
卸载：dispose(ctx) → 删插件私有存储
```

### 5.1 接口（`index.js`）

所有方法都可选，只有 `pull` 必需。全部返回 Promise，宿主负责 pump 事件循环。

```js
module.exports = {
  // 一次性：读设置、建缓存
  async init(ctx) {},

  // 登录态：宿主据此画 chip（ok / expired / missing）
  async auth(ctx) {
    return { state: "ok", account: { name: "Publieople", avatar: "https://…" } };
  },

  // 扫码：只返回二维码内容，宿主自己渲染成图；插件不碰 UI
  async login(ctx) {
    const r = await ctx.cli.run({ argv: ["bili", "login", "--json"], timeoutMs: 60000 });
    return { type: "qrcode", content: JSON.parse(r.stdout).qr_content, expiresIn: 180 };
  },

  // 动态声明流（可选；静态声明写在 plugin.json 里）
  async feeds(ctx) { return [{ id: "recommend", name: "推荐", requiresAuth: true }]; },

  // 拉一页：必须返回 { items, next }
  async pull(ctx, { feedId, limit, cursor }) {
    const r = await ctx.cli.run({ argv: ["bili", "feed", feedId, "--json", "-n", String(limit)] });
    return { items: JSON.parse(r.stdout).items.map(normalize), next: null };
  },

  // 详情（正文、媒体、完整互动数）
  async detail(ctx, item) { return { text: "", media: [] }; },

  // 评论，支持楼中楼
  async comments(ctx, item, { limit, cursor }) { return { items: [], next: null }; },

  // 卸载清理
  async dispose(ctx) {},
};
```

### 5.2 调用契约

| 规则 | 说明 |
|---|---|
| 超时 | 单次调用 ≤30s（browser 引擎 ≤90s），超时抛 `PluginTimeout`，只影响该插件 |
| 内存 | 每个插件 context 上限 64MB，超限抛 `PluginOOM` |
| 重试 | `http` 5xx/超时重试 2 次（宿主代做）；插件自己写的重试不叠加 |
| 幂等 | `pull` 必须可重复调用；`cursor` 为空表示第一页 |
| 分页 | `next` 为 `null` 表示到底；宿主只滚两页 |
| 错误 | 抛异常时宿主记 `runs` 表并在 UI 标"该平台暂不可用"，不白屏 |

---

## 6. 能力 API（`ctx`）

插件拿到的 `ctx` 是宿主注入的全部世界。没有 `require`、没有 `fetch`、没有文件系统。

### 6.1 `ctx.http`

```js
const r = await ctx.http.request({
  method: "GET",
  url: "https://api.bilibili.com/x/web-interface/popular",
  query: { ps: 20, pn: 1 },
  credential: "self",       // 宿主注入该插件平台的 cookie + UA，插件读不到明文
  timeoutMs: 15000,
});
r.status; r.headers; r.text; r.json();
```

- 代理、UA、Referer、重试由宿主统一处理（本机 7890 代理已在宿主配置里）。
- `credential: "self"` 只能取"当前插件自己"的凭证，拿不到别的平台。
- 响应体超 5MB 截断并报错，不让插件把内存吃满。

### 6.2 `ctx.browser`

给需要页面自己算签名的平台（抖音即此路线）。

```js
const s = await ctx.browser.open({ profile: "self" });   // 复用该插件的登录态
await s.goto("https://www.douyin.com/");
const resp = await s.waitResponse(/\/aweme\/v2\/web\/module\/feed\//, { timeoutMs: 30000 });
const data = await resp.json();
await s.scroll({ dy: 3000, times: 3, intervalMs: 800 });
await s.close();
```

- `profile: "self"` 使用宿主管理的该插件浏览器档案（已登录），插件拿不到 storageState 文件。
- 页面最多同时开 1 个，用完必须 `close()`；宿主超时强杀。

### 6.3 `ctx.cli`

现有 bili / xhs / dy CLI 的移植路径。

```js
const r = await ctx.cli.run({ argv: ["xhs", "feed", "--json", "-n", "20"], timeoutMs: 60000 });
r.code; r.stdout; r.stderr;
```

- `argv[0]` 必须命中 `plugin.json` 的 `cli.allow` 前缀，否则直接拒绝。
- 宿主用干净 env 启动（无 proxy 变量，避开 `[::1]` 解析崩溃）。
- 不经过 shell，不支持管道与重定向。

### 6.4 其他

| API | 用途 |
|---|---|
| `ctx.settings.get(key)` | 读用户在插件详情页填的参数（secret 项只返回布尔 `has`） |
| `ctx.storage.get/set/delete` | 插件私有 KV（按插件 + 账号隔离，不跨插件可见） |
| `ctx.cache.get/set(key, val, ttlSec)` | 拉取缓存，减少重复请求 |
| `ctx.log.info/warn/error` | 写宿主日志（凭证模式自动打码） |
| `ctx.util.clamp("1.2万")` | 万/亿 字符串转 int，和 `adapters/models.py` 同一套规则 |
| `ctx.env.demo` | `ONEFEED_DEMO=1` 时为 true，插件应改读 `fixtures/` |

### 6.5 沙箱限制（实测）

| 项 | 值 |
|---|---|
| 引擎 | QuickJS（`quickjs` Python 包，已验证：`add_callable` 绑定、Promise + `execute_pending_job` 泵、`set_memory_limit`） |
| 模块 | 每插件一个 fresh context，`module.exports` 导出（与 MusicFree 写法一致） |
| 隔离 | **每插件一个子进程**（`python -m onefeed.plugin_worker <dir>`），主进程只做调度与杀进程 |
| 超时 | 子进程级硬超时：http 30s / browser 90s / cli 60s，超时直接 terminate（实测 30.06s 杀掉死循环插件） |
| 内存 | `set_memory_limit(64MB)` |
| 禁止 | 文件、进程、网络裸接口、宿主 DB、其他插件存储、凭证明文 |
| 崩溃 | 异常拿到 JS 调用栈（脱敏后）写日志；子进程退出不影响其它插件与页面 |

> **实测坑（已写进 PoC）**：quickjs-py 的 `set_time_limit` 与宿主回调互斥——一旦设了 CPU 时间上限，JS 里调用任何 `add_callable` 都会抛 `InternalError: Can not call into Python with a time limit set`。所以 CPU 保护改由「子进程 + 主进程强杀」承担，QuickJS 只管内存与代码隔离。

---

## 7. 数据契约

插件只产出"平台无关"的字段，宿主负责拼 id、入库、排序、合并、渲染。

### 7.1 RawItem

```json
{
  "native_id": "BV1xx411c7mD",
  "kind": "video",
  "title": "为什么梯度消失不是玄学",
  "text": "正文或摘要，纯文本，≤800 字",
  "cover": "https://i0.hdslb.com/…jpg",
  "images": [],
  "url": "https://www.bilibili.com/video/BV1xx411c7mD",
  "author": { "name": "某某", "id": "12345", "avatar": "https://…" },
  "published_at": 1763000000,
  "duration": 372,
  "stats": { "view": 123456, "like": 2345, "comment": 120, "share": 30, "collect": 88 },
  "tags": ["机器学习", "数学"],
  "extra": { "reason": "你常看这个分区" }
}
```

| 字段 | 必填 | 约束 |
|---|---|---|
| `native_id` | ✅ | 平台原生 id；宿主拼成 `<pluginId>:<native_id>` |
| `kind` | ✅ | `video` / `images` / `article` / `short` / `list`（见 §8） |
| `title` | ✅ | ≤200 字，纯文本，无 HTML |
| `url` | ✅ | https，原文跳转 |
| `cover` | ❌ | https；缺失时卡片走占位样式 |
| `images` | ❌ | 图文用，最多 9 张，https |
| `text` | ❌ | 纯文本，`\n` 换行；不塞 HTML/富文本 |
| `author` | ❌ | `{name, id, avatar}`，缺 name 时用平台名 |
| `published_at` | ❌ | 秒级 unix，未知填 0 |
| `duration` | ❌ | 秒，未知填 0 |
| `stats` | ❌ | 全 int，缺失填 0；**不保证跨平台可比**，UI 按平台画 |
| `tags` | ❌ | ≤6 个 |
| `extra` | ❌ | 平台私有字段（推荐理由、节点、分区） |

### 7.2 RawComment

```json
{
  "native_id": "8848",
  "author": { "name": "某人", "avatar": "https://…" },
  "text": "说得好",
  "like": 12,
  "reply_count": 3,
  "created_at": 1763000000,
  "replies": []
}
```

`replies` 只允许一层（楼中楼再深就折叠成"展开更多"跳原平台）。

---

## 8. 统一呈现规范（用户说的"常见信息流形式"）

五种卡片形态，任何平台的内容先归到其中一种，再按模板渲染。**插件不写 UI。**

| kind | 判定 | 卡片结构 | 媒体规则 | meta 行 |
|---|---|---|---|---|
| `video` | 有视频主体 | 封面 + 时长角标 + 标题 2 行 | 横屏 16:9；竖屏按 9:16 裁切居中，右上角「竖」标 | 作者 · 播放 · 时长 · 平台标 |
| `images` | 图文/笔记 | 图组 + 标题 2 行 + 作者 | 1 图 16:9；2–3 图双列；4–9 图三列方形，右下角 `n/N` | 作者 · 赞 · 图数 · 平台标 |
| `article` | 长文/技术帖 | 左文右图（图 96×96）+ 标题 2 行 + 摘要 2 行 | 无图时文字通栏 | 作者 · 阅读 · 标签 |
| `short` | 纯文本/动态 | 文本 6 行 + 「展开」，无封面 | 无图 | 作者 · 回复数 · 时间 |
| `list` | 榜单条目 | 序号 + 标题 + 热度文本，无图 | 无图 | 热度 · 标签 |

### 8.1 缺失降级（强制，禁止出现 0 值占位）

| 缺失 | 降级 |
|---|---|
| `cover` / `images` 为空 | 平台色渐变底 + 标题首字；`images` 为空但 `kind=images` 时自动降为 `short` 样式 |
| `author.name` 空 | 显示插件 `name` |
| `published_at` 0 | 隐藏时间，不显示"1970" |
| `stats` 全 0 | 整行隐藏，不显示「0 赞」 |
| `title` 空 | 用 `text` 首行截 60 字 |
| 图片加载失败 | 灰底 + 破图图标，卡片不塌 |
| `kind` 未知 | 走 `article` 兜底，不报错 |

### 8.2 统一交互

- hover：卡片上浮 2px + 阴影；封面内 1.03 倍缩放（200ms）
- 点击：右侧抽屉；`Esc` 关闭；抽屉内「去原平台」常驻
- 右键/长按：收藏、不感兴趣、复制链接
- 平台色标：4px 竖条在卡片左侧，颜色由插件 `themeColor` 决定（缺省灰）
- 详情页固定结构：媒体区 → 标题 → 作者行 → 正文 → 标签 → 评论区（统一组件，子回复缩进 1 层）

---

## 9. 分发与安装

### 9.1 registry.json

```json
{
  "schemaVersion": 1,
  "name": "OneFeed 官方示例插件集",
  "updatedAt": "2026-11-20T00:00:00Z",
  "plugins": [
    {
      "id": "bilibili",
      "name": "哔哩哔哩",
      "version": "1.0.0",
      "description": "B 站推荐流与关注流（只读）",
      "author": "onefeed-plugins",
      "kinds": ["video"],
      "capabilities": ["http", "cli"],
      "download": "https://cdn.jsdelivr.net/gh/publieople/onefeed-plugins@main/plugins/bilibili/",
      "sha256": "…"
    }
  ]
}
```

### 9.2 三种安装入口

| 方式 | 场景 |
|---|---|
| 订阅 URL | 粘贴 registry 地址，列出可选插件，点装（演示主路径） |
| 本地文件 | 拖入 `.ofp` 或目录 |
| 粘贴代码 | 直接粘 `plugin.json` + `index.js`（懒人/教学） |

### 9.3 更新与卸载

- 只在用户点「检查更新」时比对 semver，不自动替换代码
- 更新前打快照，失败可回滚
- 卸载删插件私有存储与浏览器档案；凭证目录保留 7 天

---

## 10. 仓库划分与迁移

### 10.1 主仓库 `onefeed`

保留：宿主（前端 / FastAPI / SQLite / 管线 / Agent）、`specs/`、`fixtures/`、`probes/`（研究记录）。
移除：`adapters/`（迁到插件仓库，历史留在 git）。

### 10.2 插件仓库 `onefeed-plugins`（独立，public）

```
onefeed-plugins/
  README.md                 五分钟写一个插件
  SPEC.md                   本规范的公开版
  DISCLAIMER.md             只读、自用、不下载、不写操作
  schema/plugin.schema.json
  templates/basic/          http 引擎模板
  templates/browser/        browser 引擎模板
  plugins/bilibili/         cli 引擎，video
  plugins/xiaohongshu/      cli 引擎，images
  plugins/douyin/           browser 引擎，video
  plugins/juejin/           http 引擎，article
  plugins/v2ex/             http 引擎，short
  plugins/zhihu-hot/        http 引擎，list
  registry.json
  scripts/validate.py       清单校验 + 沙箱干跑（拿 fixtures 断言）
  scripts/build_registry.py 生成 registry + sha256
```

### 10.3 迁移映射（现有实现 → 插件）

| 现有 | 插件 | 引擎 | kind |
|---|---|---|---|
| `adapters/cli_adapters.py` 的 bili | bilibili | cli（`bili feed`） | video |
| `adapters/cli_adapters.py` 的 xhs | xiaohongshu | cli（`xhs feed`） | images |
| `adapters/douyin_browser.py` | douyin | browser（回放 `/aweme/v2/web/module/feed/`） | video |
| `adapters/simple_adapters.py` 掘金 | juejin | http | article |
| 同上 V2EX | v2ex | http | short |
| 同上 知乎日报热榜 | zhihu-hot | http | list |

验收：迁移后 `python pull_all.py` 的等价输出由宿主统一打印，字段对齐率 ≥95%。

---

## 11. 安全与风险边界

### 11.1 做

- 凭证留在宿主：插件只能"以该平台身份发请求"，读不到 cookie 明文；日志自动打码
- 能力最小化：manifest 声明 + 安装授权页逐条人话解释
- 只读：插件 API 不提供点赞/评论/发布；`cli` 白名单默认拒绝写命令
- 本地：服务只绑 `127.0.0.1`，插件代码不出本机

### 11.2 说清楚（不装样子）

插件化解决的是**主仓库内置平台实现**带来的耦合与举证问题：主仓库变成通用客户端，平台能力由用户自己安装的第三方源提供。它不解决"某个插件作者自己的行为"。对应的边界做法：

- 示例仓库只做只读、自用、公开内容；不下载视频、不去水印、不绕过付费墙
- 不内置任何平台密钥，不集中托管他人插件；订阅是用户自己填的地址
- 安装页明示"插件代码在你本机执行，只装你信任的"
- 答辩时如实说：这是工程上的解耦，法律上不构成免责承诺

---

## 12. 验收标准

| 编号 | 验收 | 复现方式 |
|---|---|---|
| AC-P1 | 清单校验器对 8 类错误输入给出可读报错（缺 id / 版本非法 / 未知能力 / cli 未声明白名单 / entry 不存在 / minHostVersion 过高 / kinds 非法 / sha256 不符） | `python scripts/validate.py --self-test` |
| AC-P2 | 宿主加载插件到列出 feeds ≤3s | 插件管理页计时打点 |
| AC-P3 | 死循环插件被 20s 时间上限杀掉，其余插件与页面正常 | 故意放入 `while(true){}` 测试插件 |
| AC-P4 | 六个示例插件迁移后 `pull_all.py` 输出与旧版字段对齐 ≥95% | 跑两版 diff 脚本 |
| AC-P5 | `ONEFEED_DEMO=1` 时插件层零网络（`ctx.env.demo` 分支读 fixtures） | 断网拔网线跑 |
| AC-P6 | 安装 / 禁用 / 卸载在 UI 完成，不重启进程 | 手动走一遍 |
| AC-P7 | 插件抛错时页面显示"该平台暂不可用"，不白屏 | 禁用网络后拉取 |

---

## 13. 时间盒与任务（T21–T28）

| 任务 | 内容 | 依赖 | 归属 |
|---|---|---|---|
| T21 | 规范 v1 + `plugin.schema.json` + `validate.py`（含自测） | — | 后端 |
| T22 | 运行时：QuickJS 沙箱 + `ctx.http` + pump / 超时 / 隔离 | T21 | 后端 |
| T23 | `ctx.browser`（Playwright 会话池）+ `ctx.cli`（白名单 + 干净 env） | T22 | 后端 |
| T24 | 插件管理：安装 / 授权 / 启用 / 卸载 / registry 订阅 | T22 | 后端 + 前端 |
| T25 | 迁移 bilibili（cli）+ zhihu-hot（http），验证两种引擎 | T23 | 后端 |
| T26 | 迁移 douyin（browser）+ xhs（cli），对齐旧 adapter 输出 | T23 | 后端 |
| T27 | 五种 kind 卡片 + 缺失降级 + 详情页统一组件 | T25 | 前端 |
| T28 | 示例仓库发布 + registry + 订阅演示 + 插件教学页 | T24 | 产品 |

里程碑：11-16 插件加载出流闭环；11-20 六插件全部可用；11-24 卡片与市场完成；11-27 冻结。

---

## 14. 风险与取舍

| 风险 | 应对 |
|---|---|
| QuickJS 无 npm，签名算法要自己写 | 优先 `cli` / `browser` 引擎；http 引擎只做纯 JSON 接口 |
| `cli` 引擎等于允许执行本机命令 | 白名单前缀 + 不走 shell + 安装授权明示；信任模型与 MusicFree 一致 |
| 迁移吃掉两天 | 逻辑 1:1 搬，不改抓取策略；先把 bilibili 跑通再批量 |
| 评委觉得"插件"是逃避 | 路演话术：插件是产品差异点（20 分钟接一个平台），风险解耦是附带结果 |
| 现场装插件失败 | 预装三个、留一个现场装；`.ofp` 本地包兜底 |

## 15. 已实测（PoC，2026-11-14）

`probes/poc_plugin_runtime.py` + `probes/plugins/zhihu-hot/`（+ `dead-loop/` 反例）：

| 验证项 | 结果 |
|---|---|
| manifest → `module.exports` → `async pull` 闭环 | ✅ 1.03s 出 5 条统一 `list` item（知乎热榜，真实网络） |
| `ctx.http.request` 从 JS 侧调用（add_callable + Promise pump） | ✅ 拿回 status/text，插件侧 `r.json()` 可用 |
| `ctx.util.clamp("442万")` 万/亿 转换 | ✅ 与 `adapters/models.py` 一致（示例输出 heat=38640000） |
| 死循环插件隔离 | ✅ 子进程 30.06s 被 kill，宿主返回 `timeout after 30s`，不崩 |
| `set_time_limit` 想省掉子进程 | ❌ 与宿主回调互斥，弃用（见 §6.5 实测坑） |

运行方式：`python probes/poc_plugin_runtime.py` / `python probes/poc_plugin_runtime.py --plugin dead-loop`。

## 16. 变更记录

| 日期 | 变更 | 触发 |
|---|---|---|
| 2026-11-14 | 初稿：宿主 / 插件 / registry 三层，QuickJS 沙箱，五 kind 呈现规范 | 用户提出插件化路线（m00608） |