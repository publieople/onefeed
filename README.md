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

宿主应用（`onefeed/`）已经能跑：`python -m onefeed` 起一个本地 Web 应用，六平台卡片混排、五种 kind 卡片、详情抽屉（含插件评论区）、一句话筛选、同题合并、插件市场（安装 / 卸载 / sha256 校验）、设置页、登录窗口、`--demo` 离线兜底。

实测（2026-11-15，本机，端口 8788）：195 条 / 6 平台；卡片统一成「平台标签 + kind + 时间 / 媒体 / 标题 / 摘要 / 作者 + 互动」，短卡片不再留大片空白；B 站抽屉能拉到 20 条真实评论（楼中楼 3 层内）；设置页可改插件目录、registry、每轮条数、评论条数、默认排序、保留天数，保存即生效；`8787` 被别的程序占用时自动改用 `8788` 并在启动日志里说明。

截图：`design/ui-feed.png`（信息流）、`design/ui-drawer.png`（详情 + 评论）、`design/ui-settings.png` / `design/ui-settings-full.png`（设置页）。

## 快速开始

环境用 **uv** 管理：依赖写在 `pyproject.toml`（fastapi / uvicorn / quickjs / playwright，dev 组加 httpx），`uv.lock` 锁版本，`.python-version` 钉 3.12。

```bash
# 1) 建环境装依赖（Python 3.12，自动读 .python-version）
uv sync

# 2) 插件工具（只装用得到的）
uv tool install bili-agent   # B 站（xiaohongshu 插件不再需要 xhs-cli，走浏览器截接口）

# 3) 前端（改了 web/ 才需要；dist 已入库，不改前端可跳过）
cd web && npm install && npm run build && cd ..

# 4) 起应用：只绑 127.0.0.1:8787，浏览器自动打开
uv run python -m onefeed            # 库空时自动拉一轮
uv run python -m onefeed --warmup   # 采集并导出 fixtures/<plugin>.json
uv run python -m onefeed --demo     # 断网演示：只读 fixtures，不碰网络

# 5) 验收
uv run python tests/run_all.py            # 七项全跑（含联网的 real / e2e）
uv run python tests/run_all.py --offline  # 跳过联网用例
```

新增依赖用 `uv add <pkg>`、只在测试用就 `uv add --dev <pkg>`，改完把 `uv.lock` 一起提交。

插件目录默认取同级 `../onefeed-plugins/plugins`（可用 `ONEFEED_PLUGINS` 覆盖）；没装的插件可以去市场页一键装，下载优先 jsDelivr，GitHub API 限流也不影响。

抖音插件用系统 Chrome 跑 headless 回放，首次会建持久档案；
状态目录默认 `~/.onefeed`，不可写时自动退回仓库内 `.onefeed/`（已 gitignore），也可用 `ONEFEED_HOME` 指定。

**登录怎么给**：设置页里点「打开登录窗口」，宿主用 Playwright 起一个**独立的 Chrome 窗口**
（profile 在 `<状态目录>/login/<plugin-id>/`，不碰你日常浏览器），你在窗口里扫码/输密码，
宿主每 2 秒读一次 cookie，看到登录态就落盘并**自动关窗**。四态分别是
`idle`（没窗口）/ `waiting`（窗口开着，等你登录）/ `ok`（拿到 cookie）/ `closed`（窗口被关掉）。
判据只认登录后才出现的 cookie（小红书 `id_token`，抖音 `sessionid` / `sessionid_ss`）。

**登录态怎么给插件**：落盘位置是 `<状态目录>/cookies/<plugin-id>.json`
（`{"cookies":[{"name","value","domain",...}]}`，也接受 `{name: value}` 的字典形式），
宿主按插件 `settings.cookieFile` → 该默认路径的顺序找到它，在 `browser` 抓取前注入。
插件始终读不到 cookie 明文。「退出」会删 cookie 文件和登录 profile，下次登录是全新窗口。

B 站不弹窗：它的登录态由本机 `bili` CLI 管，设置页只给你一条 `bili login` 命令。

**评论区是插件的可选能力**：插件在 `plugin.json` 里声明 `"features": ["comments"]`
并实现 `comments(item, opts)`，详情抽屉就会去拉评论；没声明的平台（掘金 / V2EX / 知乎 / 抖音）
会明确写「这个平台的插件没有提供评论接口」，而不是转圈或报错。

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
├── onefeed/               宿主应用本体
│   ├── app.py             FastAPI 装配（静态前端 + 插件目录解析）
│   ├── api.py             只读 API + 插件市场 + 登录 + 设置
│   ├── store.py           SQLite（items / runs / plugins，游标分页）
│   ├── service.py         RefreshRunner（串行采集、进度、剪枝）
│   ├── settings.py        设置读写（env > settings.json > 默认值）
│   ├── auth.py            登录窗口（Playwright 持久上下文 + cookie 轮询）
│   ├── market.py          registry 拉取 / 下载 / sha256 校验 / 安装
│   ├── smart.py           同题聚类、一句话筛选、推荐理由
│   └── demo.py            --demo 的离线 fixtures 装载
├── docs/                  调研记录（抖音 feed 机制、平台开放度普查）
├── design/                视觉稿与实机截图
├── web/                   前端（Vite + React + TS，dist 已入库）
├── tests/                 验收脚本，入口 run_all.py
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
