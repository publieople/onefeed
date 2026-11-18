# 007 动效与交互反馈

日期：2026-11-17
状态：已实现并通过门禁

## 1. 为什么单独立规矩

这一版之前，交互反馈是散的：有的按钮有 hover，有的没有；切页是瞬切；刷新横幅还会把整页往下推。用户的原话是「我点 B 站依旧是页面瞬间切换，胶囊和底下的页面切换依旧没有动画」，随后要求「搞个 CI/CD 来确保所有用户交互逻辑都有明确的动效设计和反馈」。

所以动效不能靠自觉，得有三样东西：**统一的 token**、**一张交互状态矩阵**、**一条能跑在测试里的门禁**。

## 2. token（web/src/motion.ts）

| 名称 | 值 | 用在哪 |
| --- | --- | --- |
| `EASE` | `[0.22, 1, 0.36, 1]` | 所有 tween 缓动，替代默认 ease-out |
| `DUR.micro` | 0.14s | 按下、图标旋转、颜色切换 |
| `DUR.base` | 0.24s | toast、面板、悬浮条 |
| `DUR.page` | 0.26s | 路由切换 |
| `DUR.list` | 0.34s | 卡片 / 列表进场 |
| `SPRING` | stiffness 420 / damping 34 / mass 0.7 | hover 与按压 |
| `listItem(i)` | delay = min(i, 11) × 0.022 | 首屏卡片错峰，最多错 11 个 |
| `pageVariants(dir)` | 进 `y: 14*dir, scale: .995`；出 `y: -10*dir` | 路由 |

CSS 侧的对应物写在 `web/src/theme.css`：全局 `button { transition: … }`、`button:active { transform: scale(.975) }`、`.rise` 进场关键帧、`.fade-in`、`.skeleton` shimmer。

## 3. 交互状态矩阵

| 交互 | 反馈 | 实现位置 |
| --- | --- | --- |
| 悬停卡片 | 上浮 2px | `Card.tsx` `whileHover` |
| 按下卡片 | 缩到 0.985 | `Card.tsx` `whileTap` |
| 按下任意按钮 | 缩到 0.975 + 颜色过渡 | `theme.css` 全局规则 |
| 切换路由 | 旧页上移淡出，新页从下 14px 淡入 | `App.tsx` `pageVariants` |
| 切页后滚动 | 复位到顶部 | `App.tsx` 监听 pathname |
| 首屏卡片进场 | 依次上浮淡入，最多错峰 240ms | `FeedPage.tsx` `listItem` |
| 市场卡片进场 | 同上，间隔 28ms | `MarketPage.tsx` |
| 详情页内容 | 标题 / 媒体 / 正文分段落入 | `ItemPage.tsx` `.rise`、`.fade-in` |
| 分段控件 | 选中块用 `layoutId` 弹簧滑动 | `FeedPage.tsx` `Seg` |
| AI 面板 | 遮罩淡入 + 面板从底部弹起 | `AiDock.tsx` `AnimatePresence` |
| 评论展开 | 高度动画 + 尾部提示淡入 | `ItemPage.tsx` |
| 设置分组 | 高度 auto↔0 + 箭头旋转 | `SettingSection.tsx` |
| 保存条 | 底部浮起，不占文档流 | `SettingsPage.tsx` |
| 进度 | 顶栏 2px 线宽度过渡，不推页面 | `TopBar.tsx` |
| 骨架 | shimmer 扫光 | `.skeleton` |
| 减弱动效 | `prefers-reduced-motion` 时全部降到 0.01ms | `theme.css` |

## 4. 两条硬约束（踩过的坑）

1. **路由容器上不能有 `transform` 或 `will-change: transform`**。页面容器一旦成为 `position: fixed` 的包含块，底部的 AI 胶囊和 toast 就会以整页为参照，跑到页面最底部看不见。`.page-shell` 只保留 `will-change: opacity`，切页只动透明度与位移的合成层，不动持久 transform。
2. **瞬时状态不能占文档流**。刷新进度条从文档流里挪进顶栏、绝对定位；未保存条从顶部 sticky 改成底部浮动。判定标准是「随状态出现或消失、又占据文档流高度」= 位移陷阱。

## 5. 门禁

三道，都能进 CI：

```bash
cd web && node scripts/check-ui.mjs          # 静态：颜色 token / 阴影 token / 时长 token
uv run python tests/run_all.py --offline     # 含 test_ui_lint.py，包住上面这条
uv run python probes/check_interactions.py   # 行为：9 项断言，跑真实 Chrome
```

静态规则（`check-ui.mjs`）：

- `color-token`：禁止 `bg-white`；`text-white` 只在同一行/附近 5 行出现 `bg-black`、`bg-paper/` 或 `style=` 时放行（平台色底上的白字是合法例外）。
- `shadow-token`：禁止写死 `rgba(20, …)` 阴影，要用 `shadow-card` / `shadow-pop`。
- `motion-token`：禁止 `duration: 0.x` 这类魔法数字，必须用 `DUR.*`；`motion.ts` 自身豁免。

豁免写法：行内或上一行加 `ui-lint-ignore <rule>`（JSX 注释形式 `{/* ui-lint-ignore color-token */}`）。

行为断言（`check_interactions.py`，9 项全过）：

1. 顶栏按钮 `transition-duration` 不为 0
2. 悬停卡片产生位移
3. 按下卡片产生缩放
4. 点击卡片后 90ms 内 `.page-shell` 处于过渡中（读 computed opacity/transform，不读 inline transition——跳转完成后 framer 会清掉它）
5. 详情页渲染出 h1 且文本非空
6. 点主题按钮后 `html.dark` 出现
7. `localStorage['onefeed.theme']` 被写入
8. 刷新后主题保留
9. 无 `pageerror`，无 `Failed to load resource` 之外的 console error（外链封面 403 是平台签名过期，不算交互缺陷）

## 6. 还没做的

- 详情页的骨架 / 内容切换还可以补一层交叉淡入，现在是骨架直接消失。
- 列表筛选后重排没有 FLIP 位移动画，只有重新进场。

## 7. 平台筛选：反色遮罩扫过，文字不动（2026-11-18）

平台 chips 走过三版：独立药丸（背景硬切）→ 单选胶囊（同一个 `motion.span` 在两项之间滑动）→ 多选分段胶囊（文字跟着父级缩放、位移，看起来在抖）→ 现在的**反色遮罩**。

### 7.1 为什么之前的文字会动

多选版把选中项塞进新的段容器，等于换了一次 DOM 父级，三件事同时发生：段容器 `initial={{scale: .86}}` 让按钮跟着缩放；合并时 `layoutId` 的段首变化导致元素被当成新元素；组与组之间的 `gap-0.5` 与段内 `gap-0` 不一致，让相邻文字横移 2px。实测 45ms 时掘金按钮 `matrix(0.9888…)`，文字 span 宽 61.2 → 60.5，合并瞬间 61.2 → 64.4。

### 7.2 现在的结构

- 所有 chip 永远是同一排 `button`，父子关系在任何一次点击里都不变，排版由浏览器自己负责。
- 高亮是一层独立遮罩：绝对定位、`pointer-events-none`、`rounded-full`、`bg-solid`，只动画 `x` 与 `width`，不参与排版。
- 遮罩里放一份与按钮内文字盒逐像素重合的**反色副本**（`text-solid-fg`），副本用 `useTransform(maskX, v => -v)` 反向平移，抵消遮罩的移动。视觉上是反色扫过去，字形一次都没位移。
- 段划分：按 `PLATFORMS` 顺序扫描选中集合，相邻的归为一段（`railAdjacent` 硬编码顺序，索引差 1 即相邻）；「全部」独占一段。
- 遮罩几何：`measure()` 量每个 button 的 `offsetLeft/offsetTop/offsetWidth/offsetHeight` 与按钮内 `[data-inner]` 的盒子；`useLayoutEffect` + `ResizeObserver`（rail 与每个 button）+ `document.fonts.ready` + `resize` 复测。
- 动画：每段一个 `RunMask`，`useMotionValue` 起于旧盒子（`seeds()` 按 x 区间重叠 > 4px 认领）再 `animate` 到新盒子，`SPRING`；消失的段由 `GhostMask` 原地淡出 180ms，避免高亮凭空消失。
- 当段容器用 `fixed` 定位时会被页面 transform 带跑，所以焦点环单独用 `z-20` 的 `ring-2 ring-ink/25` 画在遮罩之上。

### 7.3 两个必须记住的坑

1. **副本层的宽度不能是胶囊宽度**。副本子项用的是 rail 坐标（例如 `left: 430`），如果副本容器只有胶囊那 172px 宽，绝对定位子项的可用宽度会被算成负数，浏览器按最小宽度折行——「抖音117」变成两行，只看得见第一个字。修法：副本容器显式给整条轨道的宽度（`railW = max(box.x + box.w)`）。
2. **副本必须继承按钮的排版**（`text-[13px] leading-none`）。漏掉时副本按 16px 渲染，字更宽更高，和底层文字对不齐。

### 7.4 验收（`probes/check_tabrail_mask.py`）

断言四类，任何一条不过就说明「文字会动」或者「反色不对」：

- 单选 / 多选 / 拆分三个阶段，每个 `[data-inner]` 的 x 与宽度相对点击前偏差 ≤ 0.5px（实测三段全部 `none`）；
- 遮罩条数与几何：单选 1 条 88px；Ctrl 加相邻项合成 1 条 172px（等于两按钮宽度之和）；再加不相邻项拆成 2 条（172 / 114）；
- 副本正确性：每份副本的 x、宽度、高度与原字一致（≤1.5px），颜色是 `rgb(255, 255, 255)`（暗色下取反），高度不超过原字行高（不许折行）；
- 无 `pageerror`。

截图：`design/tabrail-mask-single.png`、`tabrail-mask-merged.png`、`tabrail-mask-split.png`、`tabrail-mask-dark.png`（暗色下胶囊变成浅底深字）。

### 7.5 交互（照文件管理器）

单击只留这一项；`Ctrl`/`⌘` 点击加/减一项；`Shift` 点击从锚点选一段（`Shift+Ctrl` 并入现有选择）；点「全部」或再点唯一选中项回全部；`←`/`→` 移动焦点并顺带选中。外层 `w-fit max-w-full`，内层横向滚动，选中屏幕外的项时 `scrollIntoView({inline: "nearest"})` 带回可视区。

### 7.6 单击切换也要滑（2026-11-18 补）

遮罩是「每段一个组件」，React key 早期直接用了段首平台 id。单击从「全部」切到「抖音」时 key 从 `all` 变成 `douyin`，组件被卸载重挂：旧胶囊原地淡出、新胶囊在目标位置直接出现，中间那段平移就没了。多选时看起来正常，是因为相邻合并时段首 id 往往不变。

修法是把「渲染身份」和「段首 id」拆开：

- 同一段首 id 沿用上一帧的身份；
- 只剩一段时（全部 ↔ 单个平台、单个平台之间），沿用上一帧唯一那条的身份，组件不卸载，`useMotionValue` 保留当前位置，`animate` 把 x 与 width 补到新盒子；
- 其余段按横向重叠继承（合并、拆分），继承不到才用段首 id 新建。

消失的段只给没被继承的那些做 ghost 淡出，所以单击切换全程只有一条遮罩，不会出现「旧的没了、新的闪出来」。

验收（`probes/check_tabrail_slide.py`）：点完的 520ms 内每 16ms 采一次遮罩几何。三次切换（全部→抖音、抖音→知乎、知乎→全部）都必须满足：起点与终点 x 相差 > 20px、存在严格落在两者之间的中间帧、全程遮罩条数恒为 1。实测三次都有 4–15 个中间帧（如抖音→知乎 420 → 528，中间采到 464 / 479 / 499 / 511 / 518）。截图 `design/tabrail-slide-mid.png`、`tabrail-slide-after.png`、`tabrail-slide-back.png`。

包体：416.4 kB（gzip 134.1 kB）。

## 8. 跳页：卡片长大铺满整页（2026-11-18）

点一张卡片，卡片本身从它在列表里的位置和尺寸长到整页大小，长出画面的过程中详情页在底下就位；返回时同一段路倒着走，缩回原卡片。用浏览器原生 View Transition 做，几何插值交给浏览器，两帧内容各自用 keyframes 控透明度。

### 8.1 共享元素

- `of-card`：被点的卡片（`Card.tsx` 的 `motion.article`）与详情页根部的过渡载体 `Shell`（`ItemPage.tsx` 三个分支——错误态 / 骨架 / 正文——都包在里面）共用这个名字。浏览器把两张快照的盒子从卡片矩形插值到整页矩形，这就是「卡片长大」本身；不再写死 `scale()`。
- `root`：其余部分。旧页压在**上面**（`z-index: 2` 对 `1`），延迟 0.18s、0.32s 淡出，让卡片先长大再退底页。
- 两张 `of-card` 快照叠在 `z-index: 3`；旧快照前 62% 保持不透明、之后淡到 0，新快照反过来在 62% 后才开始出现。分界放在 62% 是为了把「长大」这一段看完整，又不至于最后一下子硬切。

### 8.2 时间表（0.7s / `cubic-bezier(0.16,1,0.3,1)`）

| 时间 | 发生什么 |
| --- | --- |
| 0–62%（≈0–434ms） | 卡片从卡片矩形长到整页矩形，旧页不透明 |
| 62%–100% | 卡片继续贴合最终矩形，同时旧快照淡出、详情页浮现 |
| 180–500ms | 底页（root）淡出，被卡片盖着基本看不见 |
| 返回 | 同一组关键帧反向：详情页从整页缩到卡片矩形，列表卡片在下面淡入 |

### 8.3 返回要能落回原位

三件事缺一不可：

1. `api.ts` 的 `feedCache` 让信息流首帧就有卡片（否则返回瞬间列表是空的，快照没有右端）；
2. `FeedPage.tsx` 按 `location.state.fromId` 给那张卡片挂 `of-card` 并 `scrollIntoView({ block: "center" })`（卡片在视野外时变形会从屏幕外飞进来）；
3. `data-vt-item` 标记提供查询锚点。

### 8.4 降级

不支持 `document.startViewTransition` 或 `prefers-reduced-motion: reduce` 时，`runNavTransition` 直接 `apply()`：路由照常跳，没有过渡，不留 `nav-vt` 类。

### 8.5 五个坑

1. **详情页必须有落点**。只在正文分支挂 `of-card` 时，跳转瞬间新 DOM 里没有这个元素，浏览器只会把旧卡片淡掉、没有几何变形（实测新快照 100×0）。
2. **路由上不能留 `AnimatePresence mode="wait"`**：wait 会等旧页退场跑完才挂新页，快照拍到旧页，过渡变成「旧页动两下、新页凭空出现」。
3. **`apply()` 必须 `flushSync`**：React 默认把更新放进微任务，View Transition 回调返回就拍新快照，可能拍到旧 DOM。
4. **主题切换的 `::view-transition-*` 要收进 `html.theme-vt`**，否则换肤的斜带扫屏会套到跳页上。
5. **截图会污染时间戳**：`page.screenshot` 单张 150–250ms，在采样循环里截图会把「320ms 的帧」推到过渡结束之后（量到宽 100）。探针改成页面内 `requestAnimationFrame` 逐帧记 `performance.now()` 与伪元素宽高/透明度，点完等 900ms 一次性取回；截图另跑一轮。

### 8.6 验收

- `tests/test_nav_motion.py`（8 项静态）：共享元素三件套、两个方向的关键帧、`of-page` 已清、`theme-vt` 作用域、`Shell` 覆盖三个分支、`feedCache` 与 `data-vt-item`、降级分支与接线。
- `probes/check_card_morph.py`（18 项行为，真 Chrome）：起手宽度就是卡片宽（364px）、中途超过两倍、最终 1132px（整页宽）、前段旧页不透明、收尾旧页淡出新页到位、返回从 1132 缩回 364、无 VT / 减少动效照常跳、无 `pageerror`。
- 截图：`design/morph-enter-120.png`、`morph-enter-260.png`、`morph-back-150.png`、`morph-back-300.png`。
