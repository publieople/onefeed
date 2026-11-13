# OneFeed

> 一屏刷完你的 B 站、抖音、小红书。

上海中侨职业技术大学首届「AI+X」校园 Vibe Coding 创新黑客松参赛项目。
团队 3 人。开发方式：**spec 驱动**（先写规格，再写代码，PR 必须引用 spec 条目）。

## 它解决什么

同一个人每天要开三个 App、各刷十分钟，才能看完自己真正关心的内容。
OneFeed 把三个平台（以及技术社区）的**个人信息流**拉到一个本地面板里：

- 扫码登录一次，之后不用来回切 App
- 一条时间线混排，卡片标出来源平台，点开能看评论
- 跨平台讲同一件事的内容合成一张卡，展开看各平台怎么说
- 每条卡片能回答「为什么推给我」
- 用一句话过滤：`只看 AI 和上海相关的`

## 设计边界（先划清楚）

| 做 | 不做 |
|---|---|
| 只读自己的账号，数据只在本机 | 不写操作（不点赞、不评论、不发帖） |
| 本地起服务，浏览器访问 `localhost` | 不上云、不做多用户、不做账号体系 |
| 复用平台网页端的公开接口 | 不逆向签名、不接第三方付费接口 |
| 失败就降级（缓存 / DEMO 快照） | 不为「多一个平台」牺牲稳定性 |

## 当前状态

采集层已经跑通，五个平台能吐统一结构的数据（2026-11-13 实测）：

| 平台 | 取数方式 | 状态 |
|---|---|---|
| B 站 | `bili` CLI（已登录） | ✅ 推荐流 + 封面 + 评论 |
| 抖音 | Playwright 回放网页端（不碰签名） | ✅ 推荐流 20 条 + 热评 |
| 小红书 | `xhs` CLI | ⚠️ 待扫码登录 |
| 掘金 | 公开推荐接口 | ✅ 免登录 |
| V2EX | 公开热帖接口 | ✅（需本地代理） |
| 知乎日报 | 公开接口 | ✅ 免登录 |

前端、Agent 编排、去重合并**尚未开始**，等 `specs/001-v1-core/spec.md` 的待定项定稿。

## 快速开始

```bash
# 依赖（Python 3.11+）
uv tool install bili-agent   # B 站
uv tool install xhs-cli      # 小红书
uv pip install playwright && playwright install chromium  # 抖音回放

# 拉一轮真实数据看看
python pull_all.py bili douyin juejin --limit 5
python pull_all.py douyin --json --limit 20 > /tmp/feed.json
```

抖音 adapter 会用系统 Chrome（headed），首次运行请手动扫码登录一次。

## 目录

```
onefeed/
├── adapters/              采集层：一个平台一个实现，统一 Item/Comment
│   ├── models.py          数据模型
│   ├── base.py            Adapter 协议
│   ├── cli_adapters.py    B 站 / 小红书（子进程 + 干净 env）
│   ├── douyin_browser.py  抖音（浏览器回放）
│   └── simple_adapters.py 掘金 / V2EX / 知乎日报（HTTP）
├── specs/                 规格（唯一事实来源）
│   ├── 000-constitution.md
│   └── 001-v1-core/
│       ├── spec.md        产品规格：需求 + 验收标准 + 待定项
│       ├── plan.md        技术方案：架构、算法、排期
│       └── tasks.md       任务清单（含完成状态）
├── docs/                  调研记录（抖音 feed 机制、扩平台实测）
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
- [`docs/PLATFORM_NOTES.md`](docs/PLATFORM_NOTES.md) — 还能接哪些平台（实测）
- [`docs/DY_FEED_FINDINGS.md`](docs/DY_FEED_FINDINGS.md) — 抖音 feed 机制与签名坑

## 许可

MIT