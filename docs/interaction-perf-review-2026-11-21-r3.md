# OneFeed 第三轮交互与性能评审（2026-11-21）

> 口径：代码基线 `cec0def`（列数只跟窗口宽度走），Chrome headless 1440×900 / 390×844，本地 demo 库 961 条。
> 本轮只列**新发现或仍未处理**的问题；上一轮已修项（Confirm 热键、toast 双定时器、Lenis 空闲 rAF、栏宽补间冻结列数）已复测确认，不再计入。
> 采样脚本在 `probes/review3_*.py`，原始 JSON 在 `.onefeed/review3-*.json`。

## 一、结论速览

1. **交互层面最贵的一笔不是掉帧，是"没动静"**：Agent 一轮 45–50s，首字 0.01s 就出来，但中段最长 **19.28s** 屏幕上一个字都不变（只有一行静态「下一步…」），另有 6.0/5.9/4.1s 的静止段。这比任何 100ms 的卡顿都更像"卡死"。
2. **弱网首屏 9.4s**：Fast 3G + 4× CPU 下首张卡片 9.4s、LCP 9224ms、长任务合计 5634ms（含两段 2827/1538ms）。根因是 519KB 单包，`ItemPage` 是静态 import（主包里能 grep 到它的文案）。
3. **深列表没有上限**：滚到 252 张时 9405 个节点、13.5MB heap；961 条全量约 36k 节点。此时改列数一次 **120ms 帧 + 133ms 长任务**，换筛选也有 93ms 帧。
4. **收藏对话框仍在热键栈外**：对话框开着时按 `[` 会收起背后左栏（240→64）、按 `t` 会切主题、按 `?` 会在上面再叠一层帮助。这是本轮唯一"操作直接打穿模态"的问题。
5. 手感本身是好的：胶囊切换 **175ms** 出首张新卡（API 仅 8ms）、返回列表滚动位置恢复（1200→1162）、模态打开时滚轮不穿透、卡片菜单焦点与方向键本轮已确认正常。

## 二、代码问题

| 编号 | 位置 | 问题 | 级别 |
| --- | --- | --- | --- |
| C-01 | `web/src/pages/ItemPage.tsx:1348`、`:1437` | FavoriteDialog 只有 `useScrollLock(true)`，没有 `pushScope("dialog")`；Lightbox（:207/:251）有。导致 Esc 之外的所有 global 热键照常响应。 | P1 |
| C-02 | `web/src/App.tsx:246-271` | 全站 toast 没有 `role="status"` / `aria-live`，读屏器对「已复制」「已收藏」「开始刷新」完全静默。 | P2 |
| C-03 | `web/src/App.tsx:9`、`:12` | `FeedPage`、`ItemPage` 静态引入，只有 Market/Settings/Agent/NotFound 是 lazy；`ItemPage` 连同 Lightbox、收藏对话框、评论全部进主包（dist/index-*.js 519KB，grep 命中 ItemPage 文案）。 | P1 |
| C-04 | `web/src/components/Card.tsx:304-323`、`:391` | 卡片根节点是 `motion.a`，内部再放「稍后再看」「更多操作」两个 `<button>`：a > button 非法嵌套，36/36 张卡都有。键盘可用（swallow 生效），但语义不合规。 | P2 |
| C-05 | `web/src/pages/ItemPage.tsx:131` | 内嵌播放 iframe 有 title/allow/referrerPolicy，**没有 sandbox**。第三方页面一旦被换源，权限就是默认全量。 | P2 |
| C-06 | `web/src/pages/FeedPage.tsx:407-411` | 请求失败只有一行红字，没有「重试」；空态反而有两个动作（清空筛选 / 现在刷新）。错误态的出路比空态还少。 | P2 |
| C-07 | `web/index.html:5` | viewport 没有 `viewport-fit=cover`；全站也没有任何 `env(safe-area-inset-*)`。 | P2 |
| C-08 | `web/src/pages/SettingsPage.tsx`、`MarketPage.tsx`、`NotFound.tsx` | 不设 `document.title`：直接打开 /settings、/market 标签页是默认标题；从详情页进入则残留条目标题。 | P3 |
| C-09 | `web/index.html` | 没有 favicon（无 `web/public`），也没有 description / og。 | P3 |
| C-10 | `web/src/pages/ItemPage.tsx:611` | 详情默认 `tab="summary"`，视频/图集要切到「原文」才看得到媒体与缩略图；对视频条目多一步。 | P2（产品判断） |

## 三、交互问题

| 编号 | 场景 | 实测 | 级别 |
| --- | --- | --- | --- |
| I-01 | Agent 执行中 | 最长 **19.28s** 无任何可见变化；12s 截图里只有「下一步…」和停止键。用户无法区分"在跑"与"卡死"。 | P1 |
| I-02 | 收藏对话框 | 开框后 Tab 三次到「取消」，然后 `[` 收起左栏、`t` 切主题、`?` 叠帮助（1→2 个 dialog）。 | P1 |
| I-03 | 移动端 AI 唤起器 | 390×844 下 rect bottom=828，距底 16px，落在 iOS Home Indicator 手势区（<34px）；没有 safe-area 兜底。 | P2 |
| I-04 | 深列表改列数 | 252 张时 3→2 列：120.5ms 帧 + 133ms 长任务；用户正在"整理视图"时被打断。 | P2 |
| I-05 | 信息流失败 | 只有报错文本，没有重试按钮；用户只能整页刷新。 | P2 |
| I-06 | 移动端点按 | 58 个 <44px 命中区：顶栏四钮 36×36、分段控件 44×26、平台胶囊 25-28 高、卡片星标。 | P3 |
| I-07 | 键盘 j/k | `scrollIntoView({block:"nearest"})` 是瞬移，长列表里跨屏跳没有过渡，视线容易丢。 | P3 |

## 四、性能问题（本轮新测）

| 编号 | 场景 | 数字 |
| --- | --- | --- |
| P-01 | 冷启动（本地） | 首卡 0.813s、LCP 1628ms、CLS 0.0244；4 段长任务共 570ms；33 请求 912KB（JS 519KB）。 |
| P-02 | 冷启动（Fast 3G + 4× CPU） | 首卡 **9.4s**、LCP **9224ms**、12 段长任务共 **5634ms**（2827/1538/337/282ms）。 |
| P-03 | 深列表 | 18→252 张用 12.7s；节点 1007→9405、heap 6.8→13.5MB；首轮滚动 burst fps 55.6 / max 173ms / 长任务 176ms。961 条全量约 36k 节点。 |
| P-04 | 252 张时换筛选 | max 93.2ms、4 个 jank 帧。 |
| P-05 | 252 张时改列数 | max 120.5ms、长任务 133ms + 81ms（18 张时无长任务，说明是线性放大）。 |
| P-06 | 首屏图片 | 视口内 2 张封面 270KB：B 站 1890×1063 显示 343×193（**210KB，5.5× 过采样**）；头像 512×488 显示 16×16（204KB，32×）。 |
| P-07 | 首屏 API | 11 个请求，其中 `/api/feed?saved=1&limit=1` 2520B 只为角标计数；`/api/agent/threads` 5055B、summaries 3725B；首页 feed 27.8KB + 自动第二页 25.6KB。 |
| P-08 | 导航往返 8 次 | heap 6.3→13.6MB，强制 GC 后 8.9MB（+2.6MB）；DOM 节点稳定 1007，无泄漏。 |

补充：胶囊点击 → 首张新卡 **175ms**（feed 请求 8ms、18KB）；返回列表滚动 1200→1162，位置恢复；模态打开时滚轮 700px 不穿透；252 张之后纯滚动 74.6fps、0 长任务（滚动本身没问题，问题在批量重排与 DOM 规模）。

## 五、改进建议

### P1（这一轮就该做）

1. **给 Agent 加心跳与秒表**（I-01）。`AgentThread` 的 `live` 分支加一个 1s interval 的 elapsed 显示（「还在跑 · 12s」），并在 `AgentConsole` 里把已到达的步骤滚动可见；结果未回时给 2–3 行骨架卡。不要只靠「下一步…」这一行静态文本。
2. **FavoriteDialog 压热键栈**（C-01）。与 Lightbox 同款：`useEffect(() => { pushScope("dialog"); return popScope; }, [])`；更彻底的做法是封装 `useModalScope()`，所有 `role="dialog"` 强制使用。
3. **拆包**（C-03）。`const ItemPage = lazy(() => import("./pages/ItemPage"))`，并在卡片 hover/focus 时 `import()` 预热（已有 600ms 数据预取，顺手把模块也预取），进入详情前 await 模块即可保住 View Transition。目标：主包 <300KB。
4. **深列表设上限**（P-03/P-05）。两条低成本路线任选：
   - 卡片加 `content-visibility: auto; contain-intrinsic-size: 340px`（先验证与 `container-type` 的兼容）；
   - 或 >120 张时切 `windowing`（渲染视口 ±2 屏，其余占位）。
   同时 `useGridCols` 把卡片数量传进去：>120 张时改列数不跑 FLIP。
5. **图片降采样**（P-06）。采集层给每个平台存一份缩略 URL（B 站 `@672w_378h_1c.webp`、知乎 `_360w`、小红书 `?imageView2/2/w/720`、头像 64px 档），或服务端加 `/api/thumb?u=` 代理 + 缓存；首屏前 2 张封面 `fetchpriority="high"` 且 `loading="eager"`。

### P2（下一轮清）

6. toast 加 `role="status" aria-live="polite"`（C-02）。
7. 信息流错误态补「重试」按钮，调用同一 `load()`（C-06）。
8. 移动端补 `viewport-fit=cover` + 唤起器/底部条 `padding-bottom: max(12px, env(safe-area-inset-bottom))`（C-07/I-03）；顺手把 `100vh` 统一成 `100dvh`（Shell.tsx:161/191、AgentPage.tsx:108、AgentRail.tsx:59）。
9. 卡片结构改为 `<article>` + 绝对定位的 `<a>` 铺满 + 两个按钮 `z-index` 在上（C-04）。
10. iframe 补 `sandbox="allow-scripts allow-same-origin allow-popups allow-presentation"`（C-05）。
11. 详情页按 `kind` 决定默认页签：video / images 默认「原文」，article 默认「summary」（C-10）。
12. 一个 `useDocumentTitle()` 统一设置标题，补 favicon 与 description（C-08/C-09）。
13. 合并计数接口：`/api/counts` 返回 saved/favorites/summaries 三个数，替代三个 limit=1 的列表请求（P-07）。
14. 键盘 j/k 改成 `behavior: reduce ? "auto" : "smooth"`，并给当前卡加 1px 焦点描边（I-07）。

### P3（有空再说）

15. 统一 `DUR` 与 `D` 两套动画令牌（设计评审里"三套方言"的遗留）。
16. 卡片 hover 预取目前 600ms 双请求，键盘 focus 也会触发；可只对 `(hover: hover)` 生效，并限制同时 2 个。
17. 移动端把 36×36 的顶栏按钮加到 44×44 命中区（视觉不变，用 `::after` 扩边）。

## 六、本轮覆盖与未覆盖

**已覆盖**：冷启动（本地/弱网）、弱网首屏、长列表累积与筛选/改列、导航往返与监听器、键盘与焦点、跳过链接、toast 语义、收藏对话框热键、移动端布局与安全区、Agent 一轮静默、首屏图片字节、API 冷启动清单、卡片菜单焦点、数字输入校验、模态滚轮锁定、返回滚动恢复。

**未覆盖**：Safari/Firefox 实机、真机 iOS 手势区、多图灯箱压测（demo 库正文图仍为 0）、Agent 真实多轮上下文、设置页登录扫码全流程、市场安装（只测了卸载+撤销）、后端并发/限流。

**本轮确认已修或正常**：Confirm 热键穿透、toast 单定时器、Lenis 空闲 rAF（空闲长任务 0）、CardMenu 焦点与 ArrowDown、NumberField 空值回填与 clamp、模态滚轮锁定、返回滚动位置恢复、暗色焦点环。
