# OneFeed · 一条流

> 把 B 站、小红书、抖音的时间线拧成一条你自己的流。Agent 替你抓、替你合并、替你摘要，你只负责看。

首届「AI+X」校园 Vibe Coding 创新黑客松 · 上海中侨职业技术大学 · 2026-11-28
文档日期 2026-11-13

---

## 0. 今天已经验证过的事实

写方案之前先把三个 CLI 装上跑了一遍，下面这些是实测结果，不是推测。

| 项 | 结果 |
|---|---|
| `xhs-cli` | 装上 0.1.4，命令齐全（feed / search / read / comment / favorites / status / login） |
| `dy-cli` | 装上 0.2.2，命令齐全（trending / search / detail / comments / profile / me / live / publish） |
| `bili` | 0.8.0，已登录 Publieople（mid 324858924），stdout 恒为 JSON |
| B 站推荐流 | 跑通，单次 30 条上限，带 bvid / 标题 / 作者 / 时长 / 播放 / 点赞 / 弹幕 / 发布时间 / 理由标签 |
| B 站评论 | 跑通，一次返回 pinned + 根评论 + 前几条楼中楼，结构干净 |
| B 站封面 | slim 输出没有封面字段，要用 `--raw` 取 `pic` |
| 小红书 | 未登录，`feed --json` 待扫码后验证 |
| 抖音热榜 | **不登录就能跑**，30 条，带话题热度、封面、讨论数 |
| 抖音搜索 | **必须登录**（返回「请先登录，再继续搜索吧」） |
| 抖音关注流 | **没有对应命令**。源码里有 `/aweme/v1/web/tab/feed/` 这个地址，但 CLI 没暴露 |

**一个必须写进代码的坑**：本机 `NO_PROXY` 里含 `[::1]`，httpx 解析它时会崩（`invalid literal for int() with base 10: ':1]'`）。bili-cli 0.8.0 和 dy-cli 0.2.2 都中招。解决办法是启动子进程时传一份干净的 env（不带任何 proxy 变量），已实测 dy-cli 在干净 env 下正常返回热榜。这条决定了后端 adapter 的进程启动方式，见 `第 6 节`。

---

## 1. 一句话定位

你每天要打开三个 App 各刷十分钟。OneFeed 让你扫码登录一次，之后在一块面板里刷三个平台。

同一条新闻在三个平台被七个人讲，它给你合成一张卡；点开能看三个平台的评论；它会记住你划过什么、在哪张卡上停了三秒，并且把「为什么推给你」摊开给你看。

它是个 Agent，不是个网页收藏夹。它自己决定什么时候去抓、抓多少、哪些合并、哪些压下去。

名字候选：**OneFeed / 一条流**（首选）、混流、汇流。

---

## 2. V1 边界（写死，防止 11-28 失控）

**要做**
- B 站 + 小红书 真实数据、真实登录态、真实评论
- 抖音：热榜流（已验证可免登录）+ 登录后搜索流
- 跨平台去重合并（同一事件合成一张卡）
- 统一评论渲染（三平台评论一套组件）
- 收藏 / 不感兴趣 / 已读，并影响后续排序
- Agent 状态面板 + 站内推送 + 桌面通知

**不做**
- 服务端部署、多用户、账号体系
- 发帖 / 点赞 / 评论等写操作
- 移动端原生 App
- 无限滚动（每次 60–100 条足够）

只读是产品决策，不是妥协：合规叙事一句话说完（账号只用于读取，我们不改动任何东西），风控面积也小一个量级。

---

## 3. 用户旅程（评审看到的三分钟）

1. 首次进入 → 中间三张平台卡：B 站 / 小红书 / 抖音，各显示「未连接」
2. 点 B 站 → 弹二维码 → 手机扫 → 卡片变绿，出头像昵称
3. 点小红书 → 同样扫码（xhs-cli 支持终端二维码，我们渲染到网页）
4. 抖音 → 「已连接（热榜模式）」，橙色角标，说明关注流受限
5. 首页 → 瀑布流出现，卡片角上带平台色标
6. 滚到一张合并卡 → 「这条有 3 个平台在讲」，点开展开三条来源
7. 点一张卡 → 右侧抽屉：播放器 / 正文 / 评论区（三平台混排，带色标）
8. 点「为什么推给我」→ 展开打分：新鲜度 0.8 / 你最近看过 2 条同类 / 抖音霸屏惩罚 −0.1
9. 底部输入「只看 10 分钟以内的技术视频」→ 流原地收窄
10. 切到 Agent 面板 → 实时日志：「14:02 拉取 B 站 23 条 / 合并 4 组 / 摘要 9 条」

---

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│  Frontend  Vite + React + TS + Tailwind + framer-motion │
│  Feed / Detail Drawer / Comments / Agent Panel / Setup  │
└───────────────────────┬─────────────────────────────────┘
                        │ HTTP + SSE（Agent 日志实时推送）
┌───────────────────────▼─────────────────────────────────┐
│  Backend  FastAPI (localhost:8787)                      │
│                                                         │
│  ┌── Agent Orchestrator ─────────────────────────────┐  │
│  │  scheduler → collector → pipeline → ranker → push │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌── Adapters ───────────────────────────────────────┐  │
│  │  base.py | bilibili | xhs | douyin                │  │
│  │  统一接口，各自 spawn 对应 CLI 子进程（干净 env）  │  │
│  └───────────────────────────────────────────────────┘  │
│  ┌── Store ──────────────────────────────────────────┐  │
│  │  SQLite: items / accounts / comments / clusters   │  │
│  │          interactions / summaries / run_logs      │  │
│  └───────────────────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────────────┘
                        │ subprocess，timeout 20s + retry
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
    bili-cli        xhs-cli           dy-cli
   (已登录)        (扫码登录)     (热榜免登录)
```

**为什么用 subprocess 调 CLI 而不是 import 它们的库**：三个 CLI 互相抢依赖（都是 Alpha，Python 版本要求不同），塞进同一个进程迟早炸；子进程崩了不拖垮主进程，超时可控，升级互不影响。

**为什么是本地 Web 而不是 Electron**：6–8 小时里，Electron 的打包、原生菜单、签名全是坑；满屏浏览器就是最好的演示形态，还能加 PWA manifest「添加到桌面」。Tauri 壳留作赛后加分项。

---

## 5. 统一数据模型

```python
class Item(BaseModel):
    id: str                       # 内部 uuid
    platform: Literal["bilibili", "xhs", "douyin"]
    native_id: str
    url: str

    author: Author                # name / avatar / id / url
    title: str
    text: str | None
    media: list[Media]            # type(video|image|text) / url / cover / duration / w / h
    stats: Stats                  # view / like / comment / share / collect，口径不同各自填

    published_at: datetime
    tags: list[str]
    hot_reason: str | None        # B 站的 reason、抖音热榜的标签

    cluster_id: str | None         # 合并后指向同一事件
    summary: str | None
    signals: dict                  # 打分明细，供「为什么推给我」

class Comment(BaseModel):
    platform: str
    item_id: str
    author: Author
    text: str
    likes: int
    created_at: datetime
    replies: list["Comment"]
```

字段一律允许 None。三个平台统计口径完全不同（B 站给播放弹幕，小红书给赞藏，抖音给点赞分享），强行对齐只会造出假数据。UI 上按平台画各自的指标。

---

## 6. 适配器契约与实测能力矩阵

### 6.1 进程启动必须干净

这是今天踩到的坑，直接写进 `base.py`：

```python
def clean_env() -> dict[str, str]:
    # NO_PROXY 里的 [::1] 会让 httpx 崩，必须整份 env 重造
    env = {
        "PATH": ...,
        "SystemRoot": r"C:\Windows",
        "USERPROFILE": ...,
        "APPDATA": ..., "LOCALAPPDATA": ..., "TEMP": ...,
        "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1",
    }
    return env

async def run_cli(exe: str, args: list[str], timeout: float = 20) -> dict:
    proc = await asyncio.create_subprocess_exec(
        exe, *args, env=clean_env(),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    ...
```

### 6.2 能力矩阵（实测，2026-11-13）

| 能力 | B 站（bili 0.8.0） | 小红书（xhs 0.1.4） | 抖音（自研浏览器 adapter） |
|---|---|---|---|
| 登录态 | 已登录，本地 cookie | 二维码 / 导入 Chrome cookie | 复用 `~/.dy/cookies/default.json`，或专用 profile 首跑扫码 |
| 信息流 | feed recommend（个性化，30 条）、feed timeline（关注） | feed（探索页推荐，**需登录**） | ✅ 主推荐流 20 条/屏，未登录也出流（精选页） |
| 搜索 | search | search | dy 的 search（需登录） |
| 详情 | video info | read | 视频页 URL 直接可开 |
| 评论 | comment list（含楼中楼） | comment | ✅ 视频页自动发的 `comment/list`（首页 5 条热门 + 二级回复） |
| 封面 | `video info --raw` 取 `pic`（2.6s/条，并发 6 路） | 待验证 | feed 响应自带 douyinpic 签名 CDN 直链 |
| 输出 | 恒 JSON `{ok,data}` | `--json` | 直接拿到接口 JSON（浏览器已帮我们签名） |
| 写操作 | 有，我们不用 | 有，我们不用 | 不做 |

### 6.3 抖音不再退化

dy-cli 的 `get_feed` 走的是废弃的 `/aweme/v1/web/tab/feed/`，且缺 a_bogus / timestamp / x-secsdk-web-signature 三件套，必挂。
我们改成 **Playwright 驱动系统 Chrome 回放**，监听 `/aweme/v2/web/module/feed/` 的响应，签名交给页面自己算。
所以抖音在 V1 里是**与 B 站同级的个性化流**，不是「热榜兜底」。完整机制见 `DY_FEED_FINDINGS.md`，代码见 `adapters/douyin_browser.py`。

### 6.4 已落地的 adapter（可直接跑）

| 平台 | 文件 | 取数方式 | 状态 |
|---|---|---|---|
| B 站 | `adapters/cli_adapters.py::BiliCliAdapter` | `bili feed recommend` + 封面并发补全 | ✅ 实测 5/5 条带封面 |
| 抖音 | `adapters/douyin_browser.py::DouyinBrowserAdapter` | 浏览器回放 + 评论页轮询 | ✅ 首屏 20 条，评论 5 条 |
| 掘金 | `adapters/simple_adapters.py::JuejinAdapter` | 公开推荐接口，免登录 | ✅ 200/87KB/453ms |
| V2EX | `adapters/simple_adapters.py::V2exAdapter` | 公开热帖接口，**需本地代理** | ✅ 0.38s（走 127.0.0.1:7890） |
| 知乎日报 | `adapters/simple_adapters.py::ZhihuDailyAdapter` | 公开接口，免登录，带配图 | ✅ 当日 4 条 |
| 小红书 | `adapters/cli_adapters.py::XhsCliAdapter` | `xhs feed --json` | ⚠️ 等扫码 |

试跑入口：`python onefeed/pull_all.py douyin bili juejin --limit 10`。
扩平台的分级结论（哪些便宜、哪些别碰、实测失败原因）见 `PLATFORM_NOTES.md`。

**两条硬编码约束**（都吃过亏）：
1. `cli_adapters.clean_env()` 必须重造 env，不能继承——`NO_PROXY` 里的 `[::1]` 会让 httpx 崩。
2. `simple_adapters.http_json()` 用显式 `ProxyHandler({})` 直连，失败再依次试 `127.0.0.1:7890` / `10809`；不能让 urllib 读环境代理。

---

## 7. 登录态管理

### 三种接入方式
1. **复用 CLI 已有登录态**（首选，最省事）：调 `bili auth status` / `xhs status` 探测
2. **网页内扫码**：CLI 把二维码输出成 png，前端展示，轮询状态
3. **Cookie 导入**：从本机 Chrome 自动读取 + 手动粘贴兜底

### 状态机
```
未配置 → 连接中 → 已登录 → 即将过期(≤3天) → 已失效
                        ↘ 需重新扫码
```

首页顶部一排平台 chip：绿可用 / 黄即将过期 / 红失效 / 灰未配置。这排 chip 就是「多平台」最直观的视觉证据，也是路演第一屏。

### 安全口径（写进 README 和路演 PPT）
- 凭证只落本机（`~/.onefeed/creds.json`，用 `keyring` 走 Windows DPAPI 加密）
- 不上传、不落日志；界面上只显示尾号
- 全程只读，不代你点赞、评论、发布

---

## 8. Agent 设计

### 8.1 有状态的编排器，五个阶段

| 阶段 | 做什么 | 失败降级 |
|---|---|---|
| Scheduler | 每 15 分钟一轮，可手动「现在刷一次」 | 跳过本轮 |
| Collector | 三平台并行，单平台超时 20s | 用 SQLite 缓存，UI 标「缓存」 |
| Pipeline | 归一化 → 指纹去重 → 聚类 → 摘要 → 打标 | 摘要失败显示原文 |
| Ranker | 打分排序，写 signals | 退化为时间序 |
| Pusher | 站内流 + 桌面通知（可配早晚 digest） | 静默 |

### 8.2 去重与合并（唯一必须 AI 的地方）
1. 粗筛：标题 simhash 汉明距离 ≤ 3 → 同一条
2. 聚类：标题 + 摘要的 embedding 余弦 ≥ 0.82 归为一簇；一次几百条，暴力算就够，不用向量库
3. 合并卡：簇内互动最高的一条当主卡，其余降级成「另外 N 个平台也在讲」

embedding 走 API（任意兼容 OpenAI 的），一次批量几百条，成本可忽略。
降级链：API 挂了 → 退回 simhash + 关键词重合度，功能不中断。

### 8.3 排序公式（可解释）
```
score = 0.45 * freshness      # 24h 内线性衰减
      + 0.25 * engagement     # 平台内 z-score，避免抖音大号霸屏
      + 0.20 * interest       # 与近 50 条「停留>3s」内容的 embedding 相似度
      + 0.10 * diversity      # 同平台连续出现扣分
      - 1.00 * 已读 / 不感兴趣
```
每张卡把四项分值存进 `signals`，「为什么推给我」直接展示，不用现算。

### 8.4 自然语言过滤（低成本高回报）
输入框 → LLM 转 filter DSL：

```json
{"duration_max": 600, "tags_any": ["技术", "AI"], "platforms": ["bilibili"]}
```

前端过滤 + 高亮命中原因。做了这个，AI 感从 60 分到 90 分。

### 8.5 看得见的 Agent
右下角常驻浮标 + 可展开日志条（等宽字体，逐行滚入，带时间戳），SSE 实时推。这条日志条是整个产品最容易被记住的视觉元素。

---

## 9. 界面设计

### 布局
```
┌──────────────────────────────────────────────────────┐
│ OneFeed   [●B站 ●小红书 ●抖音]        [刷新] [设置]  │ ← 56px 顶栏
├──────────────────────────────────────────────────────┤
│  ┌────────┐ ┌────────┐ ┌────────┐                    │
│  │ 卡片   │ │ 卡片   │ │ 卡片   │                    │ 瀑布流 3 列
│  │        │ │ [合并] │ │        │                    │ 窄屏 2/1 列
│  └────────┘ └────────┘ └────────┘                    │
│                                        ┌───────────┐ │
│                                        │ Agent 日志 │ │
│  [ 只看 10 分钟以内的技术视频…       ] └───────────┘ │
└──────────────────────────────────────────────────────┘
```

### 卡片
- 平台标识克制：左上角小圆点 + 4×4 图标，取平台主色（B 站 #00A1D6、小红书 #FF2442、抖音 #FE2C55）。不做三套皮肤，会乱。
- 视频卡：封面 + 时长角标 + 居中播放按钮
- 图文卡：1–4 图轮播
- 合并卡：主卡 + 底部「+2 个平台」缩略头像条，点开展开
- hover 出三个动作：收藏 / 不感兴趣 / 打开
- 已读卡片透明度降到 0.6

### 详情抽屉（右侧 480px，spring 滑入）
- 上：原内容（B 站可内嵌播放器；小红书、抖音跳转）
- 中：AI 摘要（3 条要点，可折叠）
- 下：评论，统一渲染，每条带平台色标，支持展开二级

### 动效清单（只做这些）
| 位置 | 效果 | 时长 |
|---|---|---|
| 卡片入场 | 按列 stagger，translateY 12→0 | 240ms ease-out |
| 骨架屏 | shimmer 扫光 | 1.2s loop |
| 抽屉 | spring(260, 26) | — |
| 合并卡展开 | height auto + fade | 200ms |
| 数字变化 | 滚动计数 | 600ms |

### 必须画好的三种状态
空态（引导连接）、加载态（骨架）、错误态（「B 站连接失效，点此续期」）。精致度最容易露馅就在这三处。

---

## 10. 技术栈与目录

```
onefeed/
├── backend/
│   ├── app.py                 FastAPI + SSE
│   ├── adapters/              ← 已落地，backend 直接 import 这一层
│   │   ├── base.py            Adapter 协议（start/pull/comments/close）
│   │   ├── models.py          Item / Comment 统一模型
│   │   ├── cli_adapters.py    bili（含封面并发补全）/ xhs（登录门控）+ clean_env
│   │   ├── douyin_browser.py  浏览器回放 adapter
│   │   └── simple_adapters.py 掘金 / V2EX / 知乎日报（HTTP + 代理兜底）
│   ├── agent/
│   │   ├── orchestrator.py
│   │   ├── pipeline.py
│   │   ├── ranker.py
│   │   └── pusher.py
│   ├── store.py               SQLite + WAL
│   ├── schemas.py
│   └── config.py
├── frontend/                  Vite + React + TS + Tailwind
│   └── src/components/FeedCard, MergedCard, DetailDrawer,
│                     CommentThread, PlatformChips, AgentPanel,
│                     CommandBar, StatusBanner
├── fixtures/                  DEMO 快照
├── pull_all.py                本地试跑：多平台拉一轮、打印统一 Item
├── DY_FEED_FINDINGS.md        抖音 feed 机制调查报告
├── PLATFORM_NOTES.md          扩平台实测记录（谁便宜、谁别碰）
└── PLAN.md
```

FastAPI + Pydantic v2 / SQLite + WAL / React 18 + TS + Tailwind / framer-motion / SSE。

---

## 11. 兜底：DEMO 模式第一天就做

`ONEFEED_DEMO=1` 时全部 adapter 读 `fixtures/*.json`，零网络、零风控、零扫码。

- 路演前把三平台真实数据抓一次存进 fixtures
- 现场先跑真数据，任一平台掉线就 30 秒切 DEMO，观众看不出区别
- 另外必须录一段 3 分钟全流程录屏当最后防线

整个项目 ROI 最高的一百行。

---

## 12. 时间预算

今天是 11-13，报名 11-14 截止。

### 赛前（11-14 → 11-27，每天 1–2 小时）
| 日期 | 任务 | 交付 |
|---|---|---|
| ~~11-14/15~~ | ~~adapter 打通~~ → **已提前完成**：B 站 / 抖音 / 掘金 / V2EX / 知乎日报 五个 adapter 实测可用 | `pull_all.py` 一行出统一 Item |
| 11-14/15 | 小红书扫码 + 三平台登录态统一管理 | 六平台全绿 |
| 11-16/17 | SQLite 落库 + 缓存 + SSE 推送骨架 | 后端能跑一轮完整流水线 |
| 11-18/19 | 接 backend + 修现场时效问题 | 三平台都能吐数据 |
| 11-20/21 | 瀑布流 + 卡片 + 平台色标 | 能看 |
| 11-22 | 详情抽屉 + 评论 | 能点开 |
| 11-23 | 去重聚类 + 合并卡 | 核心卖点 |
| 11-24 | 打分 + 为什么推给我 | AI 感 |
| 11-25 | 登录配置页 + 扫码 | 演示第一屏 |
| 11-26 | DEMO 模式 + fixtures + 动效 | 不崩 |
| 11-27 | 彩排两遍 + 录兜底视频 | 敢上台 |

### 11-28 当天（只打磨，不做新功能）
- 08:30–09:30 环境确认（前一晚就该好）
- 09:30–12:30 接真实数据 + 修现场问题
- 13:30–17:00 动效 / 评论 / 细节
- 17:00–18:30 重录兜底视频
- 18:30–20:00 路演材料
- 20:00–21:00 彩排两遍

---

## 13. 路演脚本（11-29，5 分钟）

| 时长 | 内容 |
|---|---|
| 30s | 问题：三个 App、三种推荐、三份广告，同一条新闻看三遍 |
| 90s | 演示：三平台全绿 → 混排流 → 合并卡 → 评论 → 一句话过滤 |
| 60s | 为什么非 AI 不可：跨平台语义合并、个性化排序、自然语言过滤，规则写不出来 |
| 60s | 价值与扩展：宿舍 / 社团 / 校园媒体都能用 |
| 30s | 记忆点：Agent 日志条 + 「你的时间线，你说了算」 |

---

## 14. 明天要确认的

- [ ] 小红书扫码后 `feed --json` 的实际字段（封面 / 时长 / 赞藏）
- [ ] 小红书二维码能否导出 png 给前端
- [ ] 抖音登录后 `search --json-output` 的字段
- [ ] 抖音 `/tab/feed/` 能否借 API 直连拿到关注流（源码里有地址，无命令）
- [ ] 三平台连续拉 5 条会不会触发风控