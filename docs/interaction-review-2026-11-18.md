# OneFeed 前端交互设计评审（交互向）

- 日期：2026-11-18
- 范围：交互行为（任务流、状态反馈、可撤销性、键盘与指针可达性）
- 不在范围：排版、色板、字号、对比度（见 `docs/design-review-2026-11-18.md` 与 `docs/design-review-2026-11-18-v2.md`）
- 环境：本机 1280×800 Chrome，`python -m onefeed --demo --no-browser --port 8799`，库里 808 条真实条目、7 个插件
- 方法：组件源码逐行读 + 真机操作复现。文中「实测」= 我在浏览器里点出来过；「代码」= 只按源码判定，未真机复现

## 一句话结论

底层机制是可信的（筛选进 URL、返回锚定、占位防跳动都真的成立），问题集中在两处系统性缺口：**状态看得见但改不掉**（关键词筛选、AI 条件、刷新失败都只进不出），以及**异步动作没有三态**（pending/失败/回滚全靠 3.2 秒的 toast 顶，失败还会假装成功）。

---

## 1. 问题总览

| # | 级别 | 问题 | 证据 |
|---|---|---|---|
| A1 | P0 | 卡片是 `role=button` 不是链接：不能 Cmd/中键新开标签，右键没有「在新标签页打开」 | web/src/components/Card.tsx:212-233 |
| A2 | P1 | 关键词筛选在页面上不可见、不可清除；「手动筛选」提交会顺手清空平台筛选并重置时间范围 | web/src/pages/FeedPage.tsx:96-112；web/src/components/AiDock.tsx:372-379 |
| A3 | P1 | 从「同一件事还出现在」跳转后，返回直接回首页且丢筛选（实测） | web/src/pages/ItemPage.tsx:839；:437-444 |
| A4 | P1 | 详情页默认落「AI 总结」，视频落地看不到播放器；切 tab 会卸载播放器，进度归零 | web/src/pages/ItemPage.tsx:457；:751-782 |
| A5 | P2 | 评论翻页失败被伪装成「就这些了」；自动翻页与手动按钮两套机制并存 | web/src/pages/ItemPage.tsx:556-576；:579-590；:888-920 |
| A6 | P2 | 长页底部的「去原帖 / 复制链接」在文档最末，评论区越长越难触达 | web/src/pages/ItemPage.tsx:925-942 |
| B1 | P0 | 输入框一获得焦点就弹面板，桌面全透明遮罩吃掉信息流第一次点击（实测） | web/src/components/AiDock.tsx:398-405；:197-209 |
| B2 | P0 | 面板没有键盘模型：Esc 不关（实测）、无 dialog 语义、无焦点陷阱、关闭后不还焦点、Tab 顺序反向 | web/src/components/AiDock.tsx:197-234；:388-423 |
| B3 | P0 | 「停止」不停止：后端从不读取消标志，前端显示「事件流断了」，没有重试 | onefeed/agent_runtime.py:56,:71-78,:142-168；onefeed/api.py:297-302；AiDock.tsx:112-119,:171-178 |
| B4 | P1 | 流断/降级没有恢复路径：一句 flash 之外没有重试；回落本地解析时用户不知道引擎换了 | web/src/components/AiDock.tsx:66-121；:134-158 |
| B5 | P2 | 「刷一刷」只在 md 以上显示；底部输入框与全局 toast 抢同一块位置 | AiDock.tsx:406-414；web/src/App.tsx:147-160 |
| C1 | P0 | 破坏性操作零确认：卸载插件、清除所有 key、退出登录、删模型行、恢复默认值 | MarketPage.tsx:90-102,:195-202；SettingsPage.tsx:200-206,:234-244,:521-526,:568-570；AiProviders.tsx:127-133 |
| C2 | P1 | 插件开关假成功：不看响应、无 pending、无回滚，连点发两次相反请求 | web/src/pages/SettingsPage.tsx:164-173；:746-752 |
| C3 | P1 | 保存模型失效：「清除所有 key」把 baseline 置空，之后改任何设置都不再出现保存条；离开页面无提示 | web/src/pages/SettingsPage.tsx:175；:200-206 |
| C4 | P1 | 数字项无校验：`Number("")` 变 0，min/max 只是属性、没有提交路径去触发 | web/src/pages/SettingsPage.tsx:450-494 |
| C5 | P2 | 浮动保存条与 toast 同坐标叠放（z-40 / z-50），toast 会盖住保存按钮 | SettingsPage.tsx:336；:771；App.tsx:155 |
| C6 | P2 | 市场并发状态串味：一个 busy 字符串、旧 timer 掐新消息、全部更新只报第一个失败、刷新目录发两次请求 | web/src/pages/MarketPage.tsx:35-38；:41/55/69/91；:68-88；:124-133 |
| D1 | P1 | 刷新失败在界面上完全不可见：`progress.plugins[].error` 有值，但没人渲染 | web/src/App.tsx:83-105；web/src/components/TopBar.tsx:15-17；onefeed/service.py:65-68,:146-149 |
| D2 | P1 | 顶栏四个按钮都是 36×36 纯图标（触控小于 44，文案只在 hover 的 title 里） | web/src/components/TopBar.tsx:57-93 |
| D3 | P2 | 空态动作错配：筛到 0 条时唯一按钮是「现在刷新一轮」，点了清不掉筛选（实测） | web/src/pages/FeedPage.tsx:180-186；:221-233 |
| D4 | P2 | 未知路由是空白页：`/nope` 只有顶栏，没有文案也没有回去的路（实测） | web/src/App.tsx:139-144 |
| D5 | P2 | 全局 toast 无 `role=status`/`aria-live`；灯箱无 dialog 语义；图库按钮无可访问名 | App.tsx:147-160；ItemPage.tsx:185-278,:280-311 |
| D6 | P2 | 方向键直接改筛选（实测：两次 ArrowRight 把 `?p=bilibili` 变成 `?p=douyin`）；多选只能靠 Ctrl/Shift，提示藏在 aria-label 里 | web/src/components/ui/TabRail.tsx:437-479；:485-491；web/src/components/Chips.tsx:14-28 |

级别定义：P0 = 主流程断掉或对外承诺不兑现；P1 = 高频误操作、状态失真；P2 = 磨手感与一致性。

---

## 2. 主流程：信息流 → 详情 → 返回

### A1 卡片不能新开标签（P0）

现象：卡片是 `motion.article` + `role="button"`（`web/src/components/Card.tsx:218-233`），没有 `href`。中键点击、Cmd/Ctrl+点击、右键菜单「在新标签页打开」、拖拽到书签栏——聚合器里最常用的四条路全部消失。

为什么算 P0：这个产品的核心动作是「一屏扫完、挑几条慢慢看」。现在挑的方式只有一种：点进去、看完、返回、再点下一条。等于把「攒着看」这个动作从产品里删掉了。

修复：外层换成 `<a href={'/item/' + encodeURIComponent(id)}>`，`onClick` 里 `preventDefault()` 后照旧走 `runNavTransition` + `navigate`；键盘 Enter/Space 变成浏览器原生行为，`role`/`tabIndex` 都可以删。注意保留 `data-vt-item` 与 `viewTransitionName`。

### A2 关键词筛选只进不出（P1 偏 P0）

三个事实叠在一起：

1. 信息流页面上没有任何搜索框——`FilterBox` 只被 `AiDock` 的「手动筛选」引用（`web/src/components/AiDock.tsx:372-379`），而且固定传 `value="" parsed={null}`：每次打开都是空输入框，连「理解为…」的解析预览都是死代码（`web/src/components/FilterBox.tsx:41-58`）。
2. 关键词设进去之后，页面上唯一的痕迹是标题变「筛选结果」和一句「筛选出 N 条」。平台筛选有胶囊、排序有时间范围有分段控件、关键词什么都没有，没有胶囊也没有清除按钮。
3. 「手动筛选」提交时只派发 `{ keyword }`，`FeedPage` 的处理器用 `Array.isArray(detail.platforms) ? detail.platforms : []` 兜底（`web/src/pages/FeedPage.tsx:103-108`）——没传就等于空数组，于是**已选平台被清空**；`range` 同理兜底成 `all`，选中的「今天」也被重置。

实测路径：`/?p=bilibili&range=today` → 打开 AI 面板 → 手动筛选 → 输入「AI」→ 提交，URL 变成 `?q=AI`，平台和今天都没了。

修复：
- 信息流头部加一条**筛选状态条**：平台 × 时间 × 排序 × 关键词各一枚可点掉的 chip，末尾「清空筛选」。这是本评审里性价比最高的一个改动——它同时解决了 A2 的可见性和 D3 的空态问题。
- 事件载荷改成「只覆盖显式给出的字段」：`platforms === undefined ? 保持 : 设置`，`range` 同理。AI 说「今天 B 站的 AI」时三个字段都会给，不需要兜底成空。
- `FilterBox` 接上真实的 value/parsed，或者干脆从 AI 面板里挪到信息流头部，把解析结果展示出来。

### A3 同题跳转丢来源（P1，实测）

`web/src/pages/ItemPage.tsx:839` 的同题链接是裸 `<Link to>`，不带 `state`；`goBack`（:437-444）读不到 `location.state.from` 就回 `"/"`。

实测：`/?p=zhihu-hot` → 点一张「3 个平台同题」的卡 → 「同一件事还出现在」点第二条 → 点「返回」→ 落在 `/`，既不回上一条详情，`?p=zhihu-hot` 也没了。

修复：同题跳转用 `navigate(..., { state: { from: location.pathname + location.search, fromId: s.id } })`，并在标题上方给一条「← 返回上一条」的面包屑；更彻底的做法是把 `from` 塞进 URL（`?from=...`），刷新和分享也不会丢。

### A4 详情页默认不给你看内容（P1）

`tab` 初始值是 `"summary"`（:457），而 `Media` 只在 `tab === "source"` 时渲染（:766-782）。也就是说视频条目落地时播放器根本没挂载，得先点「原文」。而且 `SummaryPanel` 与 `Media` 是三元切换，切回总结再切回来，iframe/video 重新挂载，播放进度归零。

修复两档：
- 小改：`useState(kind === "video" || kind === "images" ? "source" : "summary")`，视频先给画面；总结做成「原文」上方的可折叠块，两者同屏。
- 大改：媒体区常驻，总结/原文只切换下方内容，播放器永远不卸载。

### A5 评论翻页：两套机制 + 失败伪装（P2）

- `loadMoreComments` 的 `catch` 直接 `setCommentNext(null)`（:571-574），一次网络失败立刻变成「就这些了」，用户看到的是「评论区只有 36 条」这种错误结论。
- `commentTailVisible` 一旦为真就挂 IntersectionObserver（:579-590），所以点「查看更多评论（已取 20 条）」展开的瞬间，哨兵已在 240px 视口内，立刻触发自动翻页；同时底部还会渲染「加载更多评论」按钮。同一个动作有两种入口，还有一种「什么都没有发生」的间隙。

修复：失败单独渲染「评论没取到 · 重试」；只保留一种翻页方式（推荐纯自动 + 底部状态文案，去掉按钮），或按钮为主、去掉 observer。

### A6 底部操作不可随手触达（P2）

「去 X 看原帖 / 复制链接」在文档流最末（:925-942）。知乎热榜这种长评论区，要滚到底才能去原帖。建议把这两个动作提到标题下方（与「打开原帖」并列），或做成详情页右侧/底部的常驻操作条。

---

## 3. AI 助手（AiDock）：最需要重构的一块

### B1 焦点即弹层，透明遮罩吞首击（P0，实测）

`onFocus={() => setOpen(true)}`（`AiDock.tsx:402`），一碰输入框就开面板；打开态渲染 `fixed inset-0 z-30` 的遮罩，桌面下 `md:bg-transparent`——看不见，但吃点击（:197-209，`onClick` 关面板）。

实测：点输入框 → 点信息流里的卡片 → 页面不跳转、面板关闭 → 再点一次才进详情。顶栏的主题按钮同一时刻仍然可点（遮罩被页面容器的层叠上下文关在 header 以下），所以用户的感受不是「有个弹窗」，而是「卡了一拍」。

修复：输入框 `onClick` 才开（不要 `onFocus`，回车/点发送也开）；遮罩对非模态面板要么去掉，要么 `pointer-events-none`。如果确实要拦截「点外面收起」，就把它做成真正的 dialog（见 B2），别用半透明的伪遮罩。

### B2 没有键盘模型（P0，部分实测）

- 面板打开时按 Esc，面板不关（实测；全站只有灯箱接了 Esc，`ItemPage.tsx:597-603`）。
- 面板没有 `role="dialog"`/`aria-modal`，没有焦点陷阱。DOM 顺序上，面板（:216-385）排在底部 composer（:388-423）之前，而 input 是 portal 里最后一个可聚焦元素：从输入框按 Tab 直接离开文档进浏览器 UI，Shift+Tab 才反向进面板——与视觉顺序正好相反。
- 关闭按钮（:228-234）不还焦点；点「收起」后焦点落回 body。

修复：抽一个 `Dialog/Sheet` 原语：`role=dialog`、`aria-modal`、打开时记住 `activeElement`、`Esc` 关闭、`Tab`/`Shift+Tab` 在面板内循环、关闭后 `focus()` 回触发器。DOM 顺序改成 composer 在前、面板在后（视觉上可以仍然在上面，用 `order` 或 portal 分层解决）。顺便把 `aria-live` 挂到 turn 列表上，让读屏知道 agent 说了什么。

### B3 「停止」是个假按钮（P0，跨前后端）

- 前端 `stop()` 只发 `agentCancel`，本地不清 `busy/live`（`AiDock.tsx:171-178`），状态完全交给 SSE。
- 后端 `RunState.cancel` 只被赋值、**全仓没有一处读取**（`onefeed/agent_runtime.py:56,:71-78`）；取消接口把 run 标成 `cancelled` 但不发 `done` 事件（`onefeed/api.py:297-302`）；SSE 循环发现 `status != "running"` 直接 `return`（:142-168），EventSource 收到流关闭触发 `onerror`，前端于是 `say("事件流断了，稍后再试。")`（:112-119）。
- 结果：点「停止」→ agent 继续跑工具（可能继续写文件、改收藏）→ 界面报「事件流断了」而不是「已取消」。

修复：`cancel` 标志在工具循环的每一步（以及每个工具调用前后）检查并抛 `CancelledError`；取消接口写一条 `cancelled` 事件进流；前端收到后落一条「已取消」并给「重试」。在真正能停之前，界面上不要放这个按钮。

### B4 断流与降级没有恢复路径（P1）

流断只有一句 toast 式文案，历史里没有重试按钮；`agentStart` 失败回落 `aiChat` 是静默的（:134-158），用户看不出这一轮是 Agent 在操作应用、还是本地规则在解析。

修复：失败/降级各留一条可重试的消息气泡；每条 AI 回复带一个引擎小标（Agent / 本地解析），让「它能不能操作应用」这件事可见。

### B5 移动端缺一个动作，底部位置打架（P2）

「刷一刷」`hidden md:block`（:406-414），手机上没有这个动作。composer 是 `fixed bottom-0 + pb-4`（:213），全局 toast 是 `fixed bottom-6`（`App.tsx:155`），两者恰好重叠：信息流页点刷新后的「开始刷新」会压住输入框 3.2 秒。

---

## 4. 设置与市场：管理面把风险交给了用户

### C1 破坏性操作零确认（P0）

全站 grep `confirm(|beforeunload|useBlocker` 结果为空。于是：

- 卸载插件：`MarketPage.tsx:90-102`，删本地插件目录，一个 trash 图标点下去就没了（:195-202）。
- 清除所有 key：`SettingsPage.tsx:200-206`，把 `ai_api_key` 和 `ai_providers` 一起清空，不可撤销。
- 退出登录：:234-244，删本机 cookie。
- 删模型行：`AiProviders.tsx:127-133`，点 × 立刻从表单里消失。
- 恢复默认值：:521-526，把整张表单覆盖成 defaults，也没确认。

修复：一个 `ConfirmDialog`（标题一句、后果一句、破坏性按钮红色、默认焦点在取消）。卸载要写清「会删掉本地插件目录，可重新安装」；清除 key 要写清「AI 助手会退回本地解析」。

### C2 开关会骗人（P1）

`toggle()`（:164-173）`await fetch` 之后不看 `resp.ok`，直接 flash「已启用 X」并刷新列表；失败时用户看到的是成功提示，紧接着列表又弹回原状（或者更糟：服务端没变，但提示说变了）。没有 pending 态，连点会发两次相反的 PATCH，最后一次赢。开关本身是自绘 `button`，没有 `role="switch"`/`aria-checked`（:746-752）。

修复：乐观更新 + 失败回滚 + 行内错误；按 id 维护 pending；补 `role="switch"`。同样的问题 `AiProviders.tsx:104-110` 也有一份。

### C3 保存条会永久消失（P1）

`dirty = Boolean(form && baseline && JSON.stringify(form) !== baseline)`（:175），而 `clearKeys` 里 `setBaseline("")`（:203）。空字符串是假值，于是 `dirty` 恒为 `false`——清除 key 之后，改条数、改排序、改插件目录都不会再出现「有未保存的改动」条，用户以为自动保存了。也没有 `beforeunload`/路由拦截，切到别的页面改动直接消失。

修复：baseline 始终是对象/JSON 字符串，不要用 `""` 表示「无」；加离开前的未保存拦截。

### C4 数字项没有校验（P1）

`per_plugin_limit`/`comments_limit`/`prune_days` 都是 `Number(e.target.value)`（:450-494）。清空输入框得到 `0`，`min/max` 只是属性，而这些 input 不在 `<form>` 里、没有提交动作，原生校验根本不会被触发。保存后每轮采集 0 条、或保留 0 天把库清空，都是可能的。

修复：受控字符串 + 失焦校验 + 行内错误；保存前统一 `validate()`，不合法就拦住并聚焦到第一个错项。

### C5 / C6 反馈层互相打架

- 保存条 `fixed bottom-6 z-40`（:336）与设置页 note `fixed bottom-6 z-50`（:771）同坐标：有未保存改动时去拨一下插件开关，弹出的「已启用」会盖住「保存」按钮 3.2 秒。
- 市场：`flash` 每次新建 timer 却不清旧的（:35-38），快速两次操作第一条会把第二条提前清掉；`busy` 是单个字符串（:41/55/69/91），同时更新两个插件时，先完成的 `finally setBusy("")` 会把另一张卡的 spinner 也抹掉；`updateAll` 只报 `r.failed[0].id`（:79）；「刷新目录」既 `load(true)` 又 `setReload`（:124-133），两个 effect 各发一次。

修复：toast 提到 `bottom-20` 或改成右上角堆栈；busy 用 `Set<string>`；flash 用 ref 存 timer 并 `clearTimeout`；失败列表展开成可复制的清单；刷新目录只留 `load(true)`。

---

## 5. 状态反馈与可达性

### D1 刷新失败，界面什么也不说（P1）

`/api/progress` 的 `plugins[pid].error` 是有值的（`onefeed/service.py:146-149`），状态里也有汇总 `error`（:65-68），但 `progress` 只被 `TopBar` 用来算 `done/total`（`web/src/components/TopBar.tsx:15-17`），全站没有第二处读它。轮询结束时（`App.tsx:83-105`）也只是安静地刷新列表。

所以「今天 B 站一条都没进来」在界面上不可解释：没有失败徽标、没有「哪个平台挂了」、没有重试该平台的入口。这跟用户的直觉直接冲突——他会以为是自己筛选错了。

修复：TopBar 完成态给一个结果气泡：「12/12 · 1 个平台失败」，点开列出平台 + 原因 + 「只重试这个」；失败平台在 Chips 上打个角标。

### D2 顶栏按钮小且只有图标（P1）

四个按钮都是 `h-9 w-9`（36×36，`TopBar.tsx:57-93`），低于触控 44 的下限；文案只存在于 `title`，触屏和键盘用户都拿不到。市场/设置两个 `NavLink` 连 `aria-label` 都没有，只有 `title`。

修复：至少 `h-10 w-10`；导航项在 `lg` 以上显示文字（图标 + 两字）；给两个 NavLink 补 `aria-label` 或可见文字。

### D3 空态给错了动作（P2，实测）

`/?q=zzzzzznotfound`：文案说「当前筛选下没有匹配，换个条件试试」，唯一按钮却是「现在刷新一轮」（`FeedPage.tsx:221-233`）。刷新不会清 `q`，点完还是 0 条。同一行的「筛选出 0 条，共 0 条命中」还把「已加载条数」当成「筛选结果数」在说（:180-186）——同一个数字在滚动加载后会变，读者会以为命中数在增长。

修复：空态主按钮 = 「清空筛选」（有筛选时），「刷新」降为次要；摘要改成「已显示 30 / 共 148」。

### D4 未知路由是白板（P2，实测）

`Routes` 没有 `*`（`App.tsx:139-144`），`/nope` 只剩顶栏，没有文案、没有回首页链接。

修复：`<Route path="*" element={<NotFound/>} />`，一句「这页不存在」+ 两个出口（回信息流 / 刷新）。

### D5 语义与可访问名（P2）

- 全局 toast 没有 `role="status"`/`aria-live`（`App.tsx:147-160`），读屏完全不知道刷新开始了。
- 灯箱（`ItemPage.tsx:185-278`）有 Esc 与左右键，但没有 `role="dialog"`/`aria-modal`，焦点也不进灯箱，Tab 会跑到背后的正文里。
- 图库缩略图是 `alt=""` 的 `img` 包 `button`（:280-311），按钮没有可访问名。

### D6 方向键 = 改筛选（P2，实测）

`TabRail` 的 `onKeyDown`（:470-479）收到左右键就 `choose()` + `focus()`。实测：`?p=bilibili` 下按两次 ArrowRight，URL 变成 `?p=douyin`——键盘用户没有「只移动焦点、不改变筛选」的方式，而每次按键都会触发一次 `/api/feed`。多选（Ctrl/Shift）只写在 `aria-label` 里（`Chips.tsx:14-28`），鼠标用户永远发现不了；点已选中的唯一一项会静默取消回「全部」（`TabRail.tsx:437-468`）；轨道 `overflow-x-auto` 且隐藏滚动条、没有渐隐提示（:485-491），窄屏上右边的平台是「看不见也猜不到」。

修复：左右键只移焦点，Enter/Space 才应用；或方向键进入「预览」态（焦点跟随、内容不动），Enter 确认。多选给一个可见的 hint 按钮（「多选」开关），点开后 chip 变成 checkbox 语义。滚动边缘加渐隐 + 箭头。

---

## 6. 根因

1. **没有交互原语层。** Dialog、Toast、Confirm、Switch、Busy、Segmented 全在各页手搓：`Seg`（`FeedPage.tsx:253-288`）、`TabRail`（542 行自绘）、`SettingsSection`、`AgentConsole`、`MiniRow`、两个自绘开关。于是焦点、语义、pending、失败回滚在每个页面各长一套，修一处不会传染到别处。
2. **异步动作只有「忙」这一个状态。** `busy` 是字符串或布尔，没有 `pending | ok | error` 三态，也没有重试入口；所有错误都走一个 3.2 秒就消失的 toast。结果就是假成功（C2）、失败伪装成到底（A5）、失败不可见（D1）。
3. **导航上下文靠 `location.state` 手工传递。** `from`/`fromId` 只在「点卡片」这一条路径上存在；`Link`（A3）、直接打开 URL、刷新都会丢。筛选条件已经证明 URL 是对的做法，来源也应该进 URL 或统一走 history。

---

## 7. 修复路线

**第一批（一周内，都是小改动，收益最大）**
1. A1 卡片改 `<a>`；A3 同题带 state；D4 补 404。
2. A2 筛选状态条 + 事件只为显式字段赋值；手动筛选接回真实 value/parsed。
3. B1 焦点/点击开面板 + 遮罩去掉或 `pointer-events-none`；B2 Dialog 原语（Esc/陷阱/还焦点/aria）。
4. C1 ConfirmDialog 覆盖五处破坏性操作。

**第二批（需要一点重构）**
5. B3 取消令牌贯穿工具循环 + `cancelled` 事件 + 前端「已取消/重试」。
6. A4 详情默认 tab 按 kind 决定 + 媒体区常驻。
7. C2 开关三态 + 回滚；C3 baseline 修正 + 未保存拦截；C4 表单校验。
8. D1 刷新失败可见 + 单平台重试。

**第三批（打磨）**
9. C5/C6 反馈层统一坐标与计时器；D2 顶栏尺寸与文案；D5 语义补全；D6 键盘语义；A5/A6 评论与底部操作。

## 8. 验收清单（可逐条复现）

- [ ] 卡片可中键/Cmd+点击在新标签打开；右键菜单有「在新标签页打开」
- [ ] 任意筛选组合在页面上都有可见 chip，可逐项删除，也可一键清空
- [ ] 手动筛选输入关键词不会清掉已选平台、不会把「今天」改成「全部」
- [ ] 从同题跳转后按「返回」回到上一条详情，筛选条件仍在
- [ ] AI 面板：点输入框才开；Esc 关闭；关闭后焦点回到输入框；Tab 在面板内循环
- [ ] 点「停止」后工具调用在 2 秒内停止，界面显示「已取消」并给重试
- [ ] 卸载插件 / 清除 key / 退出登录 / 恢复默认值 均有确认，取消不产生副作用
- [ ] 插件开关失败会回滚并显示原因；连点不会发出相反请求
- [ ] 改动任何设置都出现保存条；刷新页面会提示还有未保存改动
- [ ] 某平台采集失败时，顶栏能看到失败数并能只重试它
- [ ] `/nope` 有 404 文案与回首页入口
- [ ] 空态（有筛选）主按钮是「清空筛选」，摘要显示「已显示 N / 共 M」
- [ ] 信息流页触发 toast 时，AI 输入框与保存条不被遮挡

## 9. 本轮没验证的

- 窄屏真机（390px）：`hidden lg:block` 的 TOC、`hidden md:block` 的「刷一刷」、chips 横向滚动的溢出提示都只按代码判定，没在真机上看。
- 浏览器返回键的滚动恢复：没有 CDP，注入不了 script；代码上 `App.tsx:48-54` 在「无 vt state」时会 `scrollTo(0)`，逻辑上成立，但没有实测。
- Safari / Firefox 的 View Transition 降级路径。
- 真实取消一次 agent（会产生写操作），所以 B3 的后端结论来自源码 + 事件流行为，未真跑。
