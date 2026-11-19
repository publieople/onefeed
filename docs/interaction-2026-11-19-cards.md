# 卡片动作、右栏 AI 总结、侧栏与换肤的收尾（2026-11-19）

这一轮改的是「看得见但没有出口」的四处：侧栏收起时元素瞬间重排、换肤动画把顶栏晾在外面、
卡片只有「点开」一条路、右栏只有稍后再看。每条都按「现象 → 做法 → 实测」记，数字都是
1440×900 Chrome 里量出来的。

## 1. 侧栏展开/收起改成弹性平移

以前 `collapsed` 一翻，footer、按钮、会话列表当场换列，看起来是元素凭空出现并挤在一起。

现在 [web/src/agent/AgentSidebar.tsx](web/src/agent/AgentSidebar.tsx) 是两层常驻：

- `data-shell-layer="full"`：240px 完整形态；
- `data-shell-layer="rail"`：64px 图标轨。

两层都 `absolute inset-y-0 left-0`、各自固定宽度，用 CSS 交叉淡入淡出（`opacity` +
`translateX` + `visibility` 延迟 120ms 隐藏），外层只裁切不重排。列宽本身走
`shell-col` 的 `width 260ms cubic-bezier(0.22, 1.24, 0.36, 1)`，带一点回弹。

实测（页内 rAF 采样，避开 Playwright 往返延迟）：

| 方向 | 采样 | 用时 |
| --- | --- | --- |
| 收起 240 → 64 | 240 → 193 → 101 → 64 | ≈ 260ms |
| 展开 64 → 240 | 64 → 111 → 181 → 242（回弹 2px） | 276ms |

同时 full 层 opacity 1 → 0.38、rail 层 0 → 0.83，切换过程中看不到元素闪一下。

## 2. 换肤的斜带也要扫过顶栏

顶栏有常驻的 `view-transition-name: of-topbar`（导航转场时要独立成层），换肤的
clip-path 斜带只作用在 root 快照上，于是顶栏自己淡入淡出，像另一个人做的动画。

修法：[web/src/theme.css](web/src/theme.css) 里在换肤期间把顶栏的名字摘掉——

```css
html.theme-vt [data-vt="topbar"] {
  view-transition-name: none !important;
}
```

`theme-vt` 类只活到 `vt.finished`（[web/src/theme.ts](web/src/theme.ts)），所以只影响换肤这一下，
平时的导航转场仍用 `of-topbar`。实测：换肤中 `getComputedStyle(header).viewTransitionName === "none"`，
结束后恢复 `"of-topbar"`。

## 3. 卡片上的稍后再看 + 三点菜单

[web/src/components/Card.tsx](web/src/components/Card.tsx) 的 footer 右侧多了一段
（分隔线 + 星标 + ⋯），常驻而不是 hover 才出现——触屏没有 hover，键盘用户也不该先猜一下。

- 星标：`aria-pressed` 跟随收藏态，`fill` 同步；点击 `toggleSave(item.id)`。
- 三点：[web/src/components/CardMenu.tsx](web/src/components/CardMenu.tsx)，`role="menu"` +
  `role="menuitem"`，portal 到 body，右对齐；下方放不下就翻到按钮上方；点外面 / Esc /
  滚动 / 缩放都会关；↑↓ 在菜单里走。
- 菜单三项：移出/加入稍后再看、复制原平台链接（`navigator.clipboard` 失败回落
  `textarea + execCommand`，成功后派发 `onefeed:toast`「已复制原平台链接」）、
  查看 AI 总结（直接 `onOpen(item.id, linkRef, item)`，进详情页默认停在总结 tab，不重复请求）。

卡片本体是 `<a>`，所以这两个按钮都先 `preventDefault + stopPropagation`：
点收藏不能把人送走，也不能顺便开一次详情页。实测：点星标后 URL 仍是 `/`，
`aria-pressed` false → true；点「查看 AI 总结」URL 变 `/item/v2ex%3Atopic%3A1258214`。

## 4. 右栏的「AI 总结」

- 后端 [onefeed/store.py](onefeed/store.py) `summarized_items(limit=30)`：`summaries` JOIN
  `items`，按总结时间倒序，带 `summary_tldr` / `summary_at` / `summary_points`。
- 路由 [onefeed/api.py](onefeed/api.py) `GET /api/agent/summaries`（limit 1..100），
  排在 `/agent/mark` 之前，免得被通配吃掉。
- 前端 [web/src/components/SummaryList.tsx](web/src/components/SummaryList.tsx)：列表行
  封面 / 标题 / 平台点 / 时间 / 两行 tldr，点击进详情；监听 `onefeed:summary` 自动刷新。
- 入口两处：右栏 tab「AI 总结」（[web/src/components/RightRail.tsx](web/src/components/RightRail.tsx)），
  左栏 footer 的「AI 总结」带条数徽标（派发 `onefeed:rail`）。
- 详情页 [web/src/pages/ItemPage.tsx](web/src/pages/ItemPage.tsx) 总结留完就派发
  `onefeed:summary`，右栏不必等下次打开。

实测：`/api/agent/summaries?limit=2` → 200、count 2；切到 tab 后列表 30 行（库里 32 条缓存）；
点第一行进 `/item/xiaohongshu%3Anote%3A6af86588...`；900 宽下三个 tab 总宽 223px，无横向溢出。

## 验收

- `uv run python tests/run_all.py --offline` → **全部通过（25 项）**，含新增
  [tests/test_card_actions.py](tests/test_card_actions.py) 12 条（卡片按钮吞事件、菜单语义、
  三个动作、复制回落、右栏 tab、总结接口与刷新、侧栏双常驻层、换肤摘名）。
- `uv run --with pytest python -m pytest tests -q` → 96 passed。
- `cd web; node scripts/check-ui.mjs` → 没有违规。
- `npm run build` → `dist/assets/index-Oerz1hJb.js` 478.35 kB（gzip 155.15 kB）。

顺手修了两处旧账：`tests/test_store.py` 与 `tests/test_agent_runtime.py` 把 schema 版本写死成 5
（实际已是 6），改成读 `SCHEMA_VERSION`；`test_agent_runtime` 的回放断言原来赌
`recent_threads[0]` 就是刚跑完的那条，改成按 `thread_id` 取，机器慢下来不会假红。
新加的几个静态套件也登记进了 `tests/run_all.py` 的 ORDER。

## 没有验证的

- 换肤斜带扫过顶栏的目视效果：headless Chrome 的 `document.visibilityState === "hidden"`，
  View Transition 按规范被跳过；只验证到「换肤期间名字确实被摘掉、结束后恢复」。
- 无剪贴板权限时的回落路径（代码在，未在真机拒绝权限的场景下点过）。
- 触屏上的长按 / hover 差异。