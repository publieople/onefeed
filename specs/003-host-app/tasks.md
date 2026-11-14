# 任务清单（003-host-app）

> 24 个任务，编号接 002 的 T21–T28。规则同 001：一个任务 = 一次可复现的验收，做完勾掉并写日期，提交信息带编号。
> 优先级：P0 没它不能演示；P1 路演更完整；P2 有时间才做。
> 前置：002 的运行时与六个插件已完成（2026-11-14）。

## A 段：服务骨架（M1，11-15 ~ 11-16）

- [ ] **T29 SQLite 存储层**（P0）— `onefeed/store.py`：按 003 plan §3 建表，`PRAGMA user_version` 迁移，items upsert，分页查询（published_at + id 游标），runs / plugins 表读写。
  验收：`python -c "from onefeed.store import Store; s=Store(); s.upsert_items(...); print(s.page(limit=5))"` 跑两次行数不变。
- [ ] **T30 只读 API**（P0，依赖 T29）— `onefeed/api.py` + `app.py`：GET /api/feed（platform/kind/sort/cursor/limit）、GET /api/item/{id}、GET /api/health；错误体统一 `{error:{code,message,hint}}`。
  验收：`curl 127.0.0.1:8787/api/feed?limit=3` 返回 3 条；`/api/item/<不存在>` 返回 404 + hint。
- [ ] **T31 单命令入口**（P0，依赖 T30）— `onefeed/__main__.py`：`python -m onefeed`、`--demo`、`--no-browser`、`--port`；端口占用显式报错并给排查命令；启动后 800ms 再开浏览器。
  验收：连开两次，第二次报「8787 被占用（PID xxxx）」，不静默换端口。
- [ ] **T32 前端脚手架**（P0，与 T31 并行）— `web/`：Vite + React + TS + Tailwind；`npm run build` 产物 dist/ 由 FastAPI StaticFiles 挂 /；开发态 `vite proxy` 到 8787。
  验收：`python -m onefeed` 打开页面能看到占位首页；`npm run dev` 时热更新可用。

## B 段：呈现（M2，11-17 ~ 11-20）

- [ ] **T33 信息流页骨架**（P0，依赖 T30+T32）— `useFeed` hook、CSS columns 瀑布流、滚动分页、骨架屏 / 空态（引导去市场）/ 错误态（原因 + 重试）。
  验收：`python -m onefeed` 首屏出现 ≥3 平台 20 条真实卡片（M1 里程碑）。
- [ ] **T34 五种 kind 卡片**（P0，依赖 T33）— CardShell + CardVideo / CardImages / CardArticle / CardShort / CardList；实施 spec §6 降级表（无封面、无作者、无时间、无互动、未知 kind）。
  验收：本地库造六条极端数据（全缺字段），页面不破版、不显示 0 值；逐 kind 截图存 `docs/shots/`。
- [ ] **T35 详情抽屉**（P0，依赖 T33）— 480px 右侧抽屉、大图/标题/作者/时间/统计/正文/去原平台；评论区有则前 10 条、无则「该平台未提供评论」；单条刷新。
  验收：B 站条目（有评论）与知乎热榜条目（无评论）各点一次，布局都不塌。
- [ ] **T36 平台 chip 与过滤**（P0，依赖 T33）— 顶栏 chip 四态（未安装/需登录/可用/出错），点击过滤；kind 过滤下拉；状态来自 /api/plugins + /api/auth。
  验收：点「小红书」只剩小红书卡片；点回「全部」恢复；改坏插件后 chip 变红。
- [ ] **T37 刷新与进度**（P0，依赖 T30+T33）— `service.RefreshRunner` 单例 + 后台线程；POST /api/refresh（重复触发 409）；GET /api/progress；前端 1s 轮询并逐插件显示状态；完成后自动刷新列表。
  验收：点刷新后立即滚动不卡；六个插件逐个从「采集中」变「成功 N 条」；失败插件显示原因。

## C 段：插件市场（M2 收尾 + M3，11-21 ~ 11-22）

- [ ] **T38 registry 拉取与展示**（P0，依赖 T30）— `market.py`：拉 registry.json（带 1h 缓存与 ETag），合并已安装插件与 registry 条目，标出「已安装 / 可更新 / 未安装」。
  验收：`curl 127.0.0.1:8787/api/plugins` 列出六个插件与版本；断网时返回已装列表 + degraded 标记。
- [ ] **T39 安装器**（P0，依赖 T38）— 下载 zip → 目录级 sha256 校验（与 build_registry.py 同算法）→ 解到 .tmp 再原子改名 → host.discover() → 写 plugins 表 → 不重启进程出现在 chip。
  验收：删掉 douyin 目录后从市场装回，chip 出现且能拉到数据（AC-V6）。
- [ ] **T40 卸载 / 禁用 / 更新**（P0，依赖 T39）— DELETE /api/plugins/{id}、PATCH enabled、更新走同一安装流程并保留 settings。
  验收：禁用后刷新不再拉该平台；卸载后 chip 变「未安装」；更新后版本号变化。
- [ ] **T41 授权页与本地安装**（P0，依赖 T39）— 安装前弹授权页：插件 id/来源/能力逐条人话（http 能发请求、cli 能跑哪些命令、browser 能开页面）；本地 .ofp 上传安装；sha256 不符、清单错误各有明确报错。
  验收：篡改 zip 内一个字节 → 安装被拒并说明「sha256 不符」（AC-V7）；用本地 zip 装一个自建插件成功。

## D 段：登录与设置（M3，11-23）

- [ ] **T42 登录状态与 cookie 约定**（P0，依赖 T30）— `auth.py`：读 `<state>/cookies/<plugin>.json`，按插件判定表（小红书 id_token / 抖音 sessionid）给四态；GET /api/auth/{id}。
  验收：删掉 cookie 文件后 /api/auth/xiaohongshu 返回 need_login；放回后 available。
- [ ] **T43 小红书扫码登录闭环**（P0，依赖 T42）— POST /api/auth/{id}/login 起 CDP Chrome（随机端口、独立 profile），前端提示「窗口已打开请扫码」，后端轮询 URL 与 cookie，成功后导出并关浏览器。
  验收：清空 cookie → 点登录 → 手机扫码 → 面板转「可用」并出数据（AC-V8）。
- [ ] **T44 设置页**（P1，依赖 T30）— GET/PUT /api/settings：插件目录、registry 地址、每轮条数上限、默认排序；标注「立即生效 / 重启生效」。
  验收：改每轮条数为 5，刷新后每平台 ≤5 条；改 registry 为本地 file 地址能读到自定义插件。

## E 段：智能层（M4，11-24 ~ 11-26）

- [ ] **T45 跨平台去重合并**（P1，依赖 T29）— 标题归一化 + simhash（64 位，汉明距离 ≤3）聚类，写 cluster_id；同簇卡片显示「另外 N 个平台也在讲」，点开看各自来源。
  验收：人工抽查 20 条，误合并 ≤2；同簇卡片数 ≥2 时角标出现。
- [ ] **T46 排序与可解释理由**（P1，依赖 T45）— freshness 用平台内分位，engagement 用平台内 z-score 归一（不跨平台直比），排序切换按钮；卡片 hover 显示 ≤3 条真实理由（如「你关注的人 2 小时前发」「B 站同类里热度前 5%」）。
  验收：切换两种排序，前 10 条顺序明显不同；理由里出现的数字都能在数据里查到。
- [ ] **T47 每日摘要**（P2，依赖 T45）— 读缓存生成「今天新增 N 条，主要在讲 X」的一句话摘要 + 3 条代表卡；只描述已采集内容，不生成新信息。
  验收：摘要中的数字与库内条数一致；断网可用（无 LLM 时走模板）。
- [ ] **T48 一句话过滤**（P2，依赖 T33）— 输入框解析为 {platform[], keyword[], time_range}，转查询参数并用 chip 展示可删。
  验收：「只看今天 B 站的 AI」得到对应结果；解析失败的原文保留在输入框并可手动改。

## F 段：保命（M4 收尾 + 冻结，11-26 ~ 11-27）

- [ ] **T49 DEMO fixtures 与 --warmup**（P0，依赖 T37）— `demo.py`：`--warmup` 采集一轮并导出 `fixtures/<plugin>.json`；`--demo` 时 ONEFEED_DEMO=1，插件读 fixtures；fixtures 不含 cookie 与播放地址。
  验收：拔网线 + `--demo` 启动，五 kind 都出现，控制台零报错（AC-V10）。
- [ ] **T50 演示检查清单与录屏**（P0，依赖全部）— `docs/DEMO_CHECKLIST.md`：预先登录、关闭通知、投影分辨率、预热命令、兜底视频路径；录一版 3 分钟完整流程。
  验收：清单每一项都能勾；视频能完整放完不卡。
- [ ] **T51 断网彩排两遍**（P0，依赖 T49+T50）— 完整走「开会话 → 起服务 → 演示 → 装插件 → 拉详情」，记时间；第二遍不带任何提示。
  验收：两遍都在 6 分钟内完成，无手动修环境。
- [ ] **T52 冻结与发布**（P0）— tag v0.3.0，README 更新（快速开始、DEMO 命令、插件市场），release note 列本版功能；之后只修 P0 bug。
  验收：新机器 clone + 按 README 三步能跑起来。

## 里程碑对照

| 日期 | 完成 |
|---|---|
| 11-16 | A 段完成，首屏真数据（M1） |
| 11-20 | B 段完成，五种卡片 + 抽屉 + 刷新（M2） |
| 11-22 | C 段完成，市场可装卸 |
| 11-23 | D 段完成，扫码登录闭环（M3） |
| 11-26 | E 段完成（T47/T48 可砍），DEMO 就绪（M4） |
| 11-27 | F 段完成，冻结 |
