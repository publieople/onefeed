# OneFeed

> 一屏刷完你的 B 站、抖音、小红书。

上海中侨职业技术大学首届「AI+X」校园 Vibe Coding 创新黑客松参赛项目。
团队 3 人。开发方式：**spec 驱动**（先写规格，再写代码，PR 必须引用 spec 条目）。

## 它解决什么

同一个人每天要开三个 App、各刷十分钟，才能看完自己真正关心的内容。
OneFeed 把各平台的**个人信息流**拉到一个本地面板里：

- 扫码登录一次，之后不用来回切 App
- 一条时间线混排，卡片标出来源平台，点开能看评论
- 每条卡片能回答「为什么推给我」
- 用一句话过滤：`只看 AI 和上海相关的`

## 设计边界（先划清楚）

| 做 | 不做 |
|---|---|
| 只读自己的账号，数据只在本机 | 不写操作（不点赞、不评论、不发帖） |
| 本地起服务，浏览器访问 `localhost` | 不上云、不做多用户、不做账号体系 |
| 复用平台网页端的公开接口 | 不逆向签名、不接第三方付费接口 |
| 失败就降级（缓存 / DEMO 快照） | 不为「多一个平台」牺牲稳定性 |

## 架构：宿主 + 插件

主仓库只放**宿主**（运行时、数据契约、呈现、调度），一个平台的代码都不留。
每个平台是一个独立插件目录，放在另一个仓库 [`publieople/onefeed-plugins`](https://github.com/publieople/onefeed-plugins)。

```
插件（plugin.json + index.js）
        ↓ pull(ctx, {limit, cursor})
宿主：QuickJS 沙箱子进程 → 能力层（http / cli / browser）→ RawItem → 统一 Item → 卡片
```

这么拆的三个理由：

1. **平台挂了不牵连宿主**：插件抛错只影响自己那张卡，宿主照常渲染其余内容；
2. **第三方好写**：一个目录、一个 `module.exports`，不碰宿主的数据库和凭证；
3. **责任边界清楚**：宿主是播放器，插件是内容源。

插件规范见 [`specs/002-plugin-arch/spec.md`](specs/002-plugin-arch/spec.md)（完整版）与插件仓库的 `SPEC.md`（公开版）。
插件市场清单（订阅地址）：

```
https://cdn.jsdelivr.net/gh/publieople/onefeed-plugins@main/registry.json
```

## 当前状态

运行时（`plugin_runtime/`）与官方插件集已跑通，六个平台吐同一套 `Item`（2026-11-14 实测）：

| 插件 | 引擎 | 状态 |
|---|---|---|
| bilibili | `cli`（bili CLI） | ✅ 推荐流 + 封面 + 评论；关注动态 |
| douyin | `browser`（浏览器回放） | ✅ 推荐流 20 条 + 封面 |
| xiaohongshu | `browser`（截 `homefeed` 接口） | ✅ 已跑通：注入 cookie 后 15.8s 出 29 条，带封面/点赞/作者 |
| juejin | `http` | ✅ 免登录 |
| v2ex | `http` | ✅ 免登录（部分网络需代理） |
| zhihu-hot | `http` | ✅ 免登录热榜 |

前端、Agent 编排、去重合并**尚未开始**，等 `specs/001-v1-core/spec.md` 的待定项定稿。

## 快速开始

```bash
# 1) 运行时（Python 3.12）
uv venv .venv
uv pip install --python .venv\Scripts\python.exe quickjs playwright

# 2) 插件工具（只装用得到的）
uv tool install bili-agent   # B 站（xiaohongshu 插件不再需要 xhs-cli，走浏览器截接口）

# 3) 拉一轮数据（插件目录指向插件仓库）
.venv\Scripts\python.exe pull_all.py --plugins-dir ..\onefeed-plugins\plugins zhihu-hot juejin v2ex --limit 5
.venv\Scripts\python.exe pull_all.py --plugins-dir ..\onefeed-plugins\plugins bilibili --limit 3
```

抖音插件用系统 Chrome 跑 headless 回放，首次会建持久档案；
状态目录默认 `~/.onefeed`，不可写时自动退回仓库内 `.onefeed/`（已 gitignore），也可用 `ONEFEED_HOME` 指定。

**登录态怎么给插件**：客户端把 cookie 写到 `<状态目录>/cookies/<plugin-id>.json`
（`{"cookies":[{"name","value","domain",...}]}`，也接受 `{name: value}` 的字典形式），
宿主按插件 `settings.cookieFile` → 该默认路径的顺序找到它，在 `browser` 抓取前注入。
插件始终读不到 cookie 明文。

## 目录

```
onefeed/
├── plugin_runtime/        插件运行时（宿主侧，唯一允许碰平台的地方是能力层）
│   ├── manifest.py        plugin.json 校验与加载
│   ├── worker.py          QuickJS 子进程：内存上限 + 超时强杀
│   ├── capabilities.py    能力层：http / cli 白名单 / browser 回放 / storage / cache
│   ├── paths.py           状态目录解析（可写探测 + 兜底）
│   └── host.py            插件发现、调度、RawItem → Item 归一化
├── models.py              统一数据模型 Item / Comment
├── specs/                 规格（唯一事实来源）
│   ├── 000-constitution.md
│   ├── 001-v1-core/       产品规格 / 技术方案 / 任务清单
│   └── 002-plugin-arch/   插件架构提案（manifest / 生命周期 / 呈现规范 / 风险边界）
├── docs/                  调研记录（抖音 feed 机制、平台开放度普查）
├── probes/                一次性探针脚本，历史留档
└── pull_all.py            多平台试跑入口
```

## 开发流程

见 [`docs/SPEC_PROCESS.md`](docs/SPEC_PROCESS.md)。一句话版本：

```
spec 变更 → 评审通过 → 同步 tasks.md → 写代码 → PR 关联 task id → 合并
```

代码可以先写（探索性探针放 `probes/`），但**功能不先进 spec 不许动手**。

## 文档索引

- [`specs/001-v1-core/spec.md`](specs/001-v1-core/spec.md) — 产品规格与验收标准
- [`specs/001-v1-core/plan.md`](specs/001-v1-core/plan.md) — 技术方案（架构 / 排序 / 排期）
- [`specs/001-v1-core/tasks.md`](specs/001-v1-core/tasks.md) — 任务清单
- [`specs/002-plugin-arch/spec.md`](specs/002-plugin-arch/spec.md) — 插件架构（运行时选型 / manifest / 呈现规范）
- [`docs/PLATFORM_NOTES.md`](docs/PLATFORM_NOTES.md) — 还能接哪些平台（实测）
- [`docs/DY_FEED_FINDINGS.md`](docs/DY_FEED_FINDINGS.md) — 抖音 feed 机制与签名坑

## 许可

MIT
