# 技术方案（003-host-app）

> 对应 spec.md 的 FR-1..FR-10。原则：能用半小时的不花两小时，能删的不留。

## 1. 架构

```
┌────────────── 浏览器（投屏） ──────────────┐
│  React 单页：信息流 / 抽屉 / 市场 / 设置    │
└───────────────┬───────────────────────────┘
                │ fetch /api/*（同源，127.0.0.1:8787）
┌───────────────▼───────────────────────────┐
│  FastAPI（onefeed 包）                     │
│  api.py   路由        store.py  SQLite     │
│  service.py 采集编排   market.py 安装器    │
│  auth.py  登录会话    demo.py   夹具       │
└───────────────┬───────────────────────────┘
                │ 进程内调用（同一个 venv）
┌───────────────▼───────────────────────────┐
│  plugin_runtime（已完成）                  │
│  PluginHost → worker.py 子进程 → QuickJS   │
└───────────────────────────────────────────┘
```

前端构建产物 dist/ 由 FastAPI 的 StaticFiles 挂在 /，API 挂在 /api，同源免 CORS、免代理。

## 2. 目录

```
onefeed/
  onefeed/                 # 新增：宿主应用包
    __main__.py            # python -m onefeed：参数解析、起服务、开浏览器
    app.py                 # FastAPI 实例 + 静态托管 + 生命周期
    api.py                 # /api/* 路由
    store.py               # SQLite：建表、迁移、upsert、查询
    service.py             # 采集编排：pull_many + 写库 + 进度状态
    market.py              # registry 订阅、下载、sha256、解压、安装/卸载
    auth.py                # 登录会话：起 CDP Chrome、轮询 cookie、导出
    demo.py                # fixtures 读写、--warmup
    config.py              # 设置读写（state_root/settings.json）
  web/                     # 新增：前端（Vite + React + TS）
    src/pages/Feed.tsx  Plugins.tsx  Settings.tsx
    src/components/Card.tsx  CardVideo.tsx  CardImages.tsx  CardArticle.tsx  CardShort.tsx  CardList.tsx
    src/components/Drawer.tsx  ChipBar.tsx  Progress.tsx
  plugin_runtime/          # 已有，不改接口
  pull_all.py              # 已有，保留作调试入口
```

## 3. 数据层

SQLite 单文件：state_root/onefeed.db，WAL 模式，连接用 `sqlite3` 标准库（不上 ORM）。

```
PRAGMA user_version = 1;

CREATE TABLE items (
  id TEXT PRIMARY KEY,              -- "<plugin>:<native_id>"
  platform TEXT NOT NULL, kind TEXT NOT NULL,
  title TEXT, text TEXT, author TEXT, author_id TEXT, author_avatar TEXT,
  cover TEXT, images TEXT,          -- JSON 数组
  url TEXT, published_at INTEGER, duration INTEGER,
  like_count INTEGER, comment_count INTEGER, share_count INTEGER, view_count INTEGER,
  tags TEXT, extra TEXT,            -- JSON
  cluster_id TEXT, fetched_at INTEGER
);
CREATE INDEX idx_items_pub ON items(published_at DESC);
CREATE INDEX idx_items_platform ON items(platform);

CREATE TABLE runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at INTEGER, finished_at INTEGER,
  plugin TEXT, ok INTEGER, count INTEGER, error TEXT
);

CREATE TABLE plugins (
  id TEXT PRIMARY KEY, version TEXT, installed_at INTEGER,
  enabled INTEGER DEFAULT 1, sha256 TEXT, source TEXT
);
```

写入：`INSERT INTO items ... ON CONFLICT(id) DO UPDATE SET ...`，字段按名字对齐 Item.to_dict()。分页用 `WHERE (published_at, id) < (?, ?)` 的等价写法（SQLite 用 `published_at < ? OR (published_at = ? AND id < ?)`）。

## 4. API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | /api/feed?platform=&kind=&sort=&cursor=&limit= | 分页信息流，读缓存 |
| GET | /api/item/{id} | 单条详情，可选 ?refresh=1 重拉 |
| POST | /api/refresh | 触发一轮采集，返回 run_id；已有在跑返回 409 |
| GET | /api/progress | 当前轮进度：每插件状态 |
| GET | /api/plugins | 已安装插件 + registry 可用插件（含可更新标记） |
| POST | /api/plugins/install | {id, version?} 从 registry 安装 |
| POST | /api/plugins/install-local | multipart 上传 .ofp |
| DELETE | /api/plugins/{id} | 卸载 |
| PATCH | /api/plugins/{id} | {enabled: bool} |
| GET | /api/auth/{id} | 登录状态 |
| POST | /api/auth/{id}/login | 起登录会话，返回会话 id |
| GET | /api/auth/{id}/login/{sid} | 轮询扫码状态 |
| GET/PUT | /api/settings | 设置读写 |
| GET | /api/health | 版本、插件数、库大小 |

约定：错误统一 `{error: {code, message, hint}}`；HTTP 状态码用真的（404/409/422），不用 200 包错误。

## 5. 采集编排

`service.py` 里一个 `RefreshRunner`：

- 单例，进程内最多一轮；用 `threading.Lock` 抢，抢不到直接 409
- 跑在后台线程，逐个插件调 `host.pull(plugin_id)`（已经不慢：六个平台 ~40s 串行）
- 每完成一个插件：写库、写 runs、更新进度字典（排队/采集中/成功 N 条/失败原因）
- 单插件异常捕获，记 runs，不影响其他
- 前端每 1s 轮询 /api/progress，完成后自动刷新 /api/feed

超时：宿主默认按插件能力给（browser 92s、cli 92s、http 92s），这里不再叠加。

## 6. 插件市场

registry.json 结构（onefeed-plugins 已生成）：{plugins:[{id, version, name, description, capabilities, kinds, feeds, download, sha256}]}。

安装流程：

1. GET registry → 找 id（可指定 version，默认最新）
2. GET download → 若指向目录，退化为逐个文件下载（GitHub raw / jsDelivr 都支持目录索引？不支持）
   → 实现上改为：registry 的 download 字段指向 **.ofp 打包文件**（改造 build_registry.py 时加 `package` 字段），兼容期先支持「zip 包 URL」
3. 下载到 state_root/downloads/<id>-<version>.zip
4. 对 zip 内容按插件目录口径算 sha256，与 registry 比对；不符则删除并报错
5. 解压到 state_root/plugins/<id>（先解到 .tmp 再原子改名）
6. 重新 host.discover()，写 plugins 表
7. 返回 {ok, plugin}

卸载：host 移除 → 删目录 → 删表行 → chips 更新。

禁用：只写表 enabled=0，host 侧过滤掉不参与 pull。

> 迁移注意：现在 registry 的 sha256 是「目录级哈希」，而安装走 zip，两种口径必须一致。实现时把 `scripts/build_registry.py` 与宿主 market.py 共用同一段算法（rel + \0 + sha256(LF 内容) + \n 再整体 sha256），并加 `package` 字段指向 zip。

## 7. 登录

沿用已验证的 CDP 方案（probes/xhs_cdp.py）：

1. 后端起 Chrome：`--remote-debugging-port=<随机> --user-data-dir=<state>/login/<plugin>`
2. 前端显示「登录窗口已打开，请扫码」
3. 后端 Playwright `connect_over_cdp` 轮询 URL 与 cookie；页面离开 /login 或出现关键 cookie 视为成功
4. 导出 cookie → 写 `<state>/cookies/<plugin>.json`（list 格式）→ 关浏览器
5. 插件下一次 pull 时由能力层自动注入

平台差异：小红书看 `id_token`；抖音看 `sessionid`。判定表放 auth.py，新增平台只加一行。

## 8. DEMO

- `--warmup`：正常采集一轮 → 导出 `fixtures/<plugin>.json`（items 原样）
- `--demo`：设置 ONEFEED_DEMO=1 → 插件 worker 走 `ctx.env.demo` 分支读 fixtures → 服务照常
- fixtures 里只放公开可见字段，不含 cookie、不含播放地址

## 9. 前端要点

- 依赖只用：react、react-dom、vite、typescript、tailwindcss、framer-motion（动画可选）。不引 UI 库，避免样式返工。
- 瀑布流用 CSS `columns`（2/3/4 列随宽度变），不上虚拟列表；30 条一页足够。
- 卡片组件按 kind 分文件，共享 `CardShell`（平台色条、标题、作者、统计、hover 态）。
- 抽屉用 `position: fixed` + transform 过渡，不引 portal 库。
- 三态：骨架屏（首次加载）、空态（无数据：提示去市场装插件）、错误态（接口失败：显示原因 + 重试）。
- 状态管理用一个 `useFeed` hook + `useState`，不上 redux/zustand。

## 10. 已知坑（本机实测，务必带进代码）

| 坑 | 现象 | 处理 |
|---|---|---|
| venv python 写用户目录 | `PermissionError [Errno 13]` | 状态目录用 paths.state_root()，可写到仓库内 .onefeed |
| Playwright 临时目录 | `EPERM mkdtemp ...playwright-artifacts-*` | 起浏览器前调 ensure_temp_env() |
| Windows 控制台 GBK | 打印 emoji 崩 | 所有入口 `reconfigure(encoding="utf-8")` |
| 系统 Chrome 与 Playwright 内核不匹配 | `Executable doesn't exist ...chromium-1255` | 一律 `executable_path=_find_chrome()` |
| 端口占用 | 静默换端口导致投屏页面连错 | 显式报错并给出 `netstat -ano | findstr 8787` |
| jsDelivr 缓存 | registry 改了但读到旧版本 | 文档写 purge 命令；正式版用 git tag 而非 @main |
| PowerShell $args | 保留变量，赋值后参数传不进去 | 脚本改用别的变量名 |

## 11. 被否掉的方案

| 方案 | 否掉的理由 |
|---|---|
| Electron / Tauri 桌面壳 | 多一层构建与签名，投屏用浏览器足够 |
| 前端直连各平台接口 | 违背插件边界，且 CORS/签名都在前端暴露 |
| 后端渲染（Jinja + htmx） | 卡片交互（抽屉、市场安装）会写一堆手写 JS，收益不如 React |
| SSE 推进度 | 轮询 1s 已够，SSE 在 Windows 反代下有缓冲坑 |
| 上 ORM（SQLAlchemy） | 三张表，手写 SQL 更短 |
| 把 fixtures 打进 git 大文件 | 用 --warmup 生成，demo 前跑一次即可 |

## 12. 变更记录

| 日期 | 变更 | 触发 |
|---|---|---|
| 2026-11-14 | 初稿：分层、目录、SQLite schema、API 表、安装/登录/演示流程、已知坑 | 用户要求按 spec 驱动开发 |
