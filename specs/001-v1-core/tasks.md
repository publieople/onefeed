# 任务清单（001-v1-core）

规则：一个任务 = 一次可复现的验收。做完把 `[ ]` 改 `[x]` 并写日期。`[P]` 表示可与同阶段其它任务并行。

> **2026-11-14 状态变更**：采集层已迁移到插件架构（见 specs/002-plugin-arch），
> 本文件 T07–T20 属于 adapter 时代的宿主计划，**作废**，现行计划在
> [003-delivery/plan.md](../003-delivery/plan.md) 与 [003-host-app/tasks.md](../003-host-app/tasks.md)（T29 起）。
> T01–T06 保留作历史，对应实现在 onefeed-plugins/plugins/ 六个插件里。

| 优先级 | 含义 |
|---|---|
| P0 | 没有它不能演示 |
| P1 | 有它路演更完整 |
| P2 | 有时间才做 |

## 阶段〇：采集层（已完成 2026-11-13）

- [x] **T01 统一数据模型 + Adapter 协议**（P0）`adapters/models.py` `adapters/base.py` — Item/Comment dataclass，`clamp()` 处理万/亿 ｜ 2026-11-13
- [x] **T02 B 站 adapter**（P0）`adapters/cli_adapters.py` — `bili feed recommend` + 并发补封面（ThreadPoolExecutor(6)）｜ 2026-11-13
- [x] **T03 小红书 adapter**（P0）— `xhs` CLI，`status` 纯文本判登录，未登录抛明确错误 ｜ 2026-11-13
- [x] **T04 抖音 browser adapter**（P0）`adapters/douyin_browser.py` — Playwright 回放 `/aweme/v2/web/module/feed/`，滚动翻页、按时间倒序、评论轮询 ｜ 2026-11-13
- [x] **T05 掘金 / V2EX / 知乎日报 adapter**（P1）`adapters/simple_adapters.py` — 免登录 HTTP，代理候选重试 ｜ 2026-11-13
- [x] **T06 多平台试跑入口**（P0）`pull_all.py` — 逐平台 try、统一打印/JSON ｜ 2026-11-13

## 阶段一：后端骨架（已作废，迁至 003 T29–T32）

- [ ] **T07 SQLite 存储层**（P0，依赖 T01）— `items` / `comments` / `runs` 三表，WAL，`INSERT ... ON CONFLICT DO UPDATE` 按 `id` upsert，按 `published_at` 建索引。验证：同一批数据跑两次，行数不变。
- [ ] **T08 采集编排 scheduler**（P0，依赖 T02–T07）— 线程池并发跑各平台，单平台超时（抖音 90s / CLI 60s / HTTP 20s），失败退避重试 2 次，失败平台记录到 `runs` 并在返回体标 `degraded: true`。验证：故意断网，页面仍展示缓存。
- [ ] **T09 FastAPI 服务**（P0，依赖 T07；与 T10 并行）— `GET /api/feed`（分页+过滤）、`GET /api/item/{id}`（含评论）、`GET /api/platforms`（四态）、`POST /api/refresh`、`GET /api/events`（SSE 推送采集进度）。只绑 `127.0.0.1:8787`。
- [ ] **T10 前端脚手架**（P0，与 T09 并行）`[P]` — Vite + React + TS + Tailwind + framer-motion，代理到 8787，路由 `/` 与 `/settings`。

## 阶段二：界面与交互（已作废，迁至 003 T33–T37）

- [ ] **T11 信息流页**（P0，依赖 T09+T10）— 单列瀑布流，卡片（封面/标题/作者/平台色标/互动/时间），骨架屏、空态、错误态三态齐全。验收：断网时显示错误态而非白屏。
- [ ] **T12 详情抽屉**（P0，依赖 T11）— 右侧滑出，大图/标题/作者/「去原平台」/评论区（B 站楼中楼、抖音热评前 5），评论失败不影响其余部分。
- [ ] **T13 登录态管理**（P0，依赖 T10）— 顶部 chip 四态；未登录平台点击弹二维码（调后端拿 `xhs login` / 抖音扫码流程）。凭证不打印、不进日志。
- [ ] **T14 一句话过滤**（P1，依赖 T09）`[P]` — 输入框 → 解析为 `{platform[], keyword[], time_range}` → 转查询参数；解析结果以 chip 展示可删。
- [ ] **T15 动效与细节**（P1，依赖 T11–T13）— 卡片入场、抽屉缓动、chip 状态过渡、骨架屏呼吸；1366×768 投影下不破版。

## 阶段三：智能层（已作废，迁至 003 T45–T48）

- [ ] **T16 跨平台去重合并**（P0，依赖 T07+T09）— 标题 simhash（汉明距离 ≤3）+ embedding 余弦 ≥0.82 聚类；簇内互动最高为主卡；前端「另外 N 个平台也在讲」可展开。验收：人工抽查 20 条误合并 ≤2。
- [ ] **T17 排序与可解释性**（P0，依赖 T16）— `freshness` 用平台内分位数，`engagement` 用平台内 z-score 后归一（不跨平台直比），`interest` 从已读/停留信号估计；每卡生成 ≤3 条真实理由。
- [ ] **T18 Agent 推送**（P1，依赖 T17）— 每 30 分钟一轮；生成「今天新增 N 条值得看 + 一句主题」；打开页面顶部展示。禁止编造未采集内容。

## 阶段四：演示保命（已作废，迁至 003 T49–T52）

- [ ] **T19 DEMO 兜底**（P0，依赖 T07）— `ONEFEED_DEMO=1` 零网络启动，读 `fixtures/`；30 秒内可切换；启动脚本 `demo.bat` / `demo.sh`。
- [ ] **T20 演示检查清单 + 录屏**（P0，依赖全部）— 11-26 前录一版完整 3 分钟兜底视频；11-27 前跑一遍断网彩排；清单含「浏览器标签预先登录、关闭系统通知、投影分辨率验证」。

## 里程碑（仅为历史，现行见 003-delivery/plan.md §2）

| 日期 | 目标 |
|---|---|
| 11-15 | T07–T10 完成，页面能显示真实数据 |
| 11-18 | T11–T13 完成，可点开看评论 |
| 11-22 | T16–T17 完成，排序与合并可用 |
| 11-25 | T14/T15/T18/T19 完成，功能冻结 |
| 11-27 | T20 完成，只修 bug |
