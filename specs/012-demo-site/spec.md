# 012 静态演示站（GitHub Pages）

日期：2026-11-22
状态：实现中

## 1. 目标与非目标

目标：

- `https://publieople.github.io/onefeed/` 上一个可以直接打开的只读演示：真实前端 + 一份抓取快照，不联网、不登录。
- 演示站与本地实例共用同一套前端代码、同一套响应形状，差别只在数据从哪来。
- README 能说清「演示站能看什么，想真用得在本机跑」。

非目标（明确不做）：

- 不在浏览器里抓平台、不装插件、不登录任何平台账号。
- 不把任何凭证（cookie / SESSDATA / OAuth token / AI key）写进 localStorage、sessionStorage 或静态文件。
- 不做多用户服务：没有后端进程、没有账号体系、没有同步。

## 2. 为什么不能「在网页里填登录态」

三条互相独立的否决理由：

1. **取不到。** B 站、小红书、知乎、抖音的登录 cookie 是 `HttpOnly` 且绑在平台域上。页面从 `publieople.github.io` 发起跨站请求，既读不到 cookie，带凭证也会被 `SameSite` 拦掉。
2. **存不住也守不住。** localStorage 是明文、同源脚本可读，一次 XSS 全丢。演示站是公开页面，「让用户把主账号 cookie 粘进陌生网页」本身就不该成为产品动作。
3. **违宪章。** `specs/000-constitution.md` 第 2 条：只读自己的账号、不向任何第三方服务器上传用户数据或凭证、服务只监听 127.0.0.1。登录必须发生在用户本机的宿主进程里，cookie 留在 `~/.onefeed/browser/<plugin>`。

同理，插件也不能在静态站安装：插件是 Python 包 + QuickJS / Playwright 运行时，Pages 上没有文件系统，也没有进程。

## 3. 架构

- **构建期开关**：`VITE_DEMO=1` 打开演示分支，`VITE_BASE=/<repo>/` 给项目页设 base。
- **数据**：`scripts/export_demo.py` 用真实 `Store` upsert `fixtures/*.json` → `smart.cluster` → `TestClient` 截 `/api/feed`、`/api/health`、`/api/summary`、`/api/settings`，写成 `web/public/demo/api.json`。字段形状与本地实例完全一致，只抹掉 `db` / `state_dir` / `plugins_dir` 这类本机路径。
- **前端**：`web/src/demo.ts` 在 `VITE_DEMO=1` 时接管 `getJSON` / `postJSON` / `putJSON` / `deleteJSON`，按 URL 路由到快照。GET 只读；写操作返回明确拒绝；SSE（总结 / 对话 / Agent）直接给降级文案，不发请求。
- **视觉**：`health.demo === true` 时复用现有提示条，改文案为「静态快照」；设置页显示「离线演示」。

## 4. 路由与部署

- 项目页的 `base` 是 `/<repo>/`；`BrowserRouter` 的 `basename` 取 `import.meta.env.BASE_URL` 去掉末尾斜杠。
- 深链（`/settings`、`/item/...`）靠 `404.html` = `index.html` 兜底：Pages 对未知路径回 404.html，前端路由自己接管。
- `.github/workflows/pages.yml`：push `main` 或手动触发；python job 导出快照，node job 构建，`upload-pages-artifact` + `deploy-pages`。
- 一次性设置：仓库 Settings → Pages → Source 选「GitHub Actions」。这一步只能网页上点，工作流改不了。

## 5. 演示站能做什么

| 能 | 不能（有明确文案） |
| --- | --- |
| 看信息流、切换平台/类型筛选、切排序 | 刷新抓取（「静态演示不抓取」） |
| 搜索框（本地子串匹配） | 保存设置（「静态演示不能保存设置」） |
| 切主题、开合侧栏、卡片菜单 | 登录平台（`can_login: false`） |
| 打开详情抽屉骨架、看降级提示 | AI 总结 / 对话 / Agent（「演示站没有模型」） |
| 点外链回平台原页面 | 装插件、改插件目录、市场更新 |

时间筛选有个适配：fixtures 是历史快照，「今天」按快照里最新一条的时间起算，不是真实现在。否则点「今天」永远是空的。

## 6. 验收

- `uv run python scripts/export_demo.py` 离线可跑；产物 < 2 MB、条目 ≥ 30、平台 ≥ 5、每条有 `like_count`、无 `http://` 图片地址。
- `VITE_DEMO=1 VITE_BASE=/onefeed/ npm run build` 通过；`dist/404.html` 存在。
- 演示站里上述「能」的一列全部可用；「不能」的一列都出现文案而不是白屏或转圈。
- 本机 `npm run dev`（不带 `VITE_DEMO`）行为不变，`/api` 仍代理到 8787。
- `tests/test_demo_snapshot.py` 进 `tests/run_all.py` 的 ORDER，离线全绿。

## 7. 改动清单

- `scripts/export_demo.py`：快照导出。
- `web/src/demo.ts`：前端只读适配层；`web/src/api.ts` 四个 helper 接上分流。
- `web/vite.config.ts`（`base`）、`web/src/vite-env.d.ts`、`web/src/main.tsx`（basename）、`web/src/layout/Shell.tsx`（提示条文案）。
- `.github/workflows/pages.yml`、`tests/test_demo_snapshot.py`、`tests/run_all.py`、`README.md`。
