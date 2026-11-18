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

### 7.6 选中动效按状态分三种（2026-11-18，含初版「一律就地生长」的修正）

初版是「不管怎么点都原地长出来」，于是单选换平台时旧胶囊淡出、新胶囊从窄条长开，看起来像一截黑条在轨道上挪。现在按这一帧的选中状态分流，三种走法：

1. **单选平移**：`slide = 上一帧选中数 ≤ 1 && 这一帧选中数 ≤ 1`。沿用同一块遮罩（id 无条件继承、不设 `seed`），`RunMask` 从当前 motion value 继续 Spring 到新盒子——是同一枚胶囊滑过去，不是旧的散、新的长。
2. **多选、相邻已有选中**：新段带着已选项一起变长，`carried` = 段内上一帧已选的 chip，`seed` = carried 盒子的并集。遮罩从相邻那段长过去，新芯片被依次盖住，全程不露白；**不撒淡影**。
3. **多选、左右都没选**（含多选状态下点一个全新平台）：carried 为空且有新项 → 标 `born`，`seed` 取以被点 chip（`primary`，Shift 选段时取段内的那一枚）中心为轴、宽 `w0 = max(18, min(30, round(box.w * 0.45)))` 的窄条，同时撒一圈 `BloomPill` 淡影。表现为从点击中心扩散出一枚新胶囊。

身份：slide 时无条件沿用上一帧唯一那段的 id；其余先按同段首 `key` 继承，再按横向重叠 > 4px 继承，都没有才取 `key`。React key 仍是 `id + ":" + items.length`：合并 / 拆分会重挂一次以读取新 seed，单选平移两侧长度都是 1，不重挂，动画才连得上。

拆分 / 收缩的段没有新项，`seed` 取与它重叠的旧段并集，就地缩回去；被去掉的那截由 GhostMask 原地淡出（absorbed 规则见 7.7）。

**必须记住的坑**：比较上一帧不能用「signature 变了才跑」。单选平移会沿用同一个 id，signature（`id:长度`）恰好不变，effect 不跑，`seen` 停在上一帧；下一次 Ctrl 追加就会把已选中的段误判成新生。实测症状：Ctrl 加掘金时 t≈47ms 出现 31.4px 的窄条、原来的 88px 直接消失，变成从点击中心冒出来而不是从相邻段长出去。改成 `useLayoutEffect` 每次提交都比较一次，代价只是几次数组比较。

淡影只在 `born` 段撒：列表最多留 8 个，每个 `onAnimationComplete` 后自清；平移、相邻跟长、拆分都不撒。ghost 的清理定时器不在 effect cleanup 里取消（见 7.7），连点不会留下永久元素。

验收（`probes/check_tabrail_spread.py`）：页面内 rAF 采 900ms；遮罩按 `:scope > div[aria-hidden]` 且背景非透明取，淡影按 `:scope > span[aria-hidden]` 且背景非透明取（焦点环也是 `span[aria-hidden]`，但背景透明，不能数进去）。三段状态各断言：

- **全部 → 抖音（平移）**：全程恰好 1 条遮罩，x 从 0 连续滑到 270（8 个中间帧），末帧几何误差 ≤ 1.5px，**无淡影**；
- **抖音 → Ctrl 加掘金（相邻扩散）**：最窄帧 = 抖音宽 88（±6px），出现 88–169 的中间宽度，末帧 172.27（= 两枚 chip 之和），**无淡影**；
- **+ Ctrl 知乎（中心扩散）**：出现两条遮罩，新段起点宽 31.6px、中心与知乎 chip 中心误差 ≤ 4px，淡影宽度 = chip 宽且透明度递减，末帧两条；
- **连点** 4 次（间隔 90ms）后等 1.4s：遮罩恰好 1 条、淡影 0 个、无 pageerror。

截图由 `probes/shot_tabrail_modes.py` 抓中间帧：`design/tabrail-mode-slide.png`（平移途中）、`tabrail-mode-adjacent.png`（从抖音那段长出去）、`tabrail-mode-center.png`（知乎中心扩散 + 淡影）。

采样方式注意：`page.evaluate` 的往返有几十毫秒，在 Python 里循环「等 16ms → 读一次几何」量到的是几十毫秒前的状态，动画早跑完了。必须把采样循环放进页面（`window.__frames`，rAF 里记 `performance.now()` 与几何），点完等 900ms 再一次性取回。

### 7.7 中间插一项不再闪白（2026-11-18 补）

先选中 B 站和抖音（两段），再 Ctrl 点中间的小红书，会出现几十毫秒的「白底浅字」抖动。原因有三层：

1. 旧的两条胶囊走 GhostMask 淡出，新合成的那条还在按 spring 从 0 长出来；
2. 新条的 `useMotionValue` 初值就是目标盒子，那一瞬间它只有「小红书」那么宽，左右两边是普通按钮的白底；
3. GhostMask 的清理 `setTimeout` 写在 `useEffect` 的 cleanup 里——下一次选择会先 cleanup，把定时器取消掉，幽灵胶囊永久留在 DOM，还会盖在新胶囊上面。

修法：

- **seed 并集**：每个 run 除了目标盒子 `box`，再算一个 `seed`：段内已有选中项时取这些 chip 的并集，纯拆分 / 收缩时取与它横向重叠 > 4px 的旧段并集（`min(x)` 到 `max(x+w)`）。`RunMask` 用 seed 初始化 `useMotionValue`，再用 `animate` 走到 `box`。中间插一项时 seed 恰好是三枚芯片的总宽，遮罩一上来就盖满整段，没有露白；相邻追加时 seed 就是旧段本身，长过去的动画照旧。这条只在非 `born` 段上生效——`born` 段故意从窄条开始（§7.6）。
- **React key 带上 `items.length`**：`run.id + ":" + run.items.length`。合并 / 拆分必须重挂一次组件，新的 seed 才会被读取；「全部 ↔ 单个平台」两侧长度都是 1，不重挂。
- **GhostMask 增加 `absorbed`**：被新 run 的盒子完全包住（x ≤ +1、右边界 ≥、|y| ≤ 1、|h| ≤ 1）时直接 `opacity: 1`，等新遮罩接力；清理定时器改成 620ms（被吸收）/ 260ms，而且不再在 cleanup 里 `clearTimeout`——它会留在 DOM 里直到自己到期，但被新遮罩盖着看不见。

验收（`probes/check_tabrail_merge.py`）：选 B 站 + 抖音 → Ctrl 加小红书后，遮罩必须并成一条、宽度等于三枚芯片宽度之和（281 vs 276，±10），且**只在 `aria-pressed=true` 的帧上检查覆盖**（点击到 React 提交之间的白底是正常的过渡态）。实测 51 帧无露白，连点三次后幽灵胶囊归零。

包体：423.3 kB（gzip 136.6 kB）。

## 8. 跳页：卡片长大铺满整页（2026-11-18）

点一张卡片，卡片本身从它在列表里的位置和尺寸长到整页大小，长出画面的过程中详情页在底下就位；返回时同一段路倒着走，缩回原卡片。用浏览器原生 View Transition 做，几何插值交给浏览器，两帧内容各自用 keyframes 控透明度。

### 8.1 共享元素

- `of-card`：被点的卡片（`Card.tsx` 的 `motion.article`）与详情页根部的过渡载体 `Shell`（`ItemPage.tsx` 三个分支——错误态 / 骨架 / 正文——都包在里面）共用这个名字。浏览器把两张快照的盒子从卡片矩形插值到整页矩形，这就是「卡片长大」本身；不再写死 `scale()`。
- `root`：其余部分。旧页压在**上面**（`z-index: 2` 对 `1`），延迟 0.18s、0.32s 淡出，让卡片先长大再退底页。
- 两张 `of-card` 快照叠在 `z-index: 3`。**进场时旧卡片快照直接 `opacity: 0`**——它只是 364px 的缩略图被放大到整页，1080p 铺开就是一团糊，看着像加载失败；进场只留几何插值，画面由新页面自己给（`nav-card-in` 从 0.55 淡到 1）。返回方向相反：留详情页那张高清快照缩回卡片，卡片快照不显示（`html.nav-vt.nav-vt-back` 两条规则对调）。

### 8.2 时间表（0.42s / `cubic-bezier(0.16,1,0.3,1)`）

| 时间 | 发生什么 |
| --- | --- |
| 0–420ms | 卡片从卡片矩形长到整页矩形，新页面同时从 55% 透明度浮到 100% |
| 40–240ms | 底页（root）淡出，被卡片盖着基本看不见 |
| 返回 | 同一段路倒着走：详情页快照从整页缩回卡片矩形（420ms），列表在下面直接可见 |

0.7s 太长（用户反馈「切个页像慢动作」），压到 0.42s；expo-out 前 30% 就走完大半距离，观感是「一下就张开了，尾巴轻轻收住」。

### 8.3 返回要能落回原位

三件事缺一不可：

1. `api.ts` 的 `feedCache` 让信息流首帧就有卡片（否则返回瞬间列表是空的，快照没有右端）；
2. `FeedPage.tsx` 按 `location.state.fromId` 给那张卡片挂 `of-card` 并 `scrollIntoView({ block: "center" })`（卡片在视野外时变形会从屏幕外飞进来）；
3. `data-vt-item` 标记提供查询锚点。

### 8.4 降级

不支持 `document.startViewTransition` 或 `prefers-reduced-motion: reduce` 时，`runNavTransition` 直接 `apply()`：路由照常跳，没有过渡，不留 `nav-vt` 类。

### 8.5 六个坑

1. **详情页必须有落点**。只在正文分支挂 `of-card` 时，跳转瞬间新 DOM 里没有这个元素，浏览器只会把旧卡片淡掉、没有几何变形（实测新快照 100×0）。
2. **路由上不能留 `AnimatePresence mode="wait"`**：wait 会等旧页退场跑完才挂新页，快照拍到旧页，过渡变成「旧页动两下、新页凭空出现」。
3. **`apply()` 必须 `flushSync`**：React 默认把更新放进微任务，View Transition 回调返回就拍新快照，可能拍到旧 DOM。
4. **主题切换的 `::view-transition-*` 要收进 `html.theme-vt`**，否则换肤的斜带扫屏会套到跳页上。
5. **截图会污染时间戳**：`page.screenshot` 单张 150–250ms，在采样循环里截图会把「320ms 的帧」推到过渡结束之后（量到宽 100）。探针改成页面内 `requestAnimationFrame` 逐帧记 `performance.now()` 与伪元素宽高/透明度，点完等 900ms 一次性取回；截图另跑一轮。
6. **别拿缩略图当进场画面**：旧卡片快照只有列表里那么大（364px），浏览器把它拉到整页后是放大的低清图，糊得像加载失败。进场一律 `old(of-card){ animation: none; opacity: 0 }`，只保留几何插值。

### 8.6 验收

- `tests/test_nav_motion.py`（9 项静态）：共享元素三件套、`nav-card-in`、旧卡片快照被隐藏（`animation: none;\n  opacity: 0`）、`nav-vt-back` 两个方向、`of-page` 与 `nav-card-out` 已清、`theme-vt` 作用域、`Shell` 覆盖三个分支、`feedCache` 与 `data-vt-item`、降级分支与接线。
- `probes/check_card_morph.py`（19 项行为，真 Chrome）：进场起手宽度误差 ≤ 15%、中途 > 1.8×卡片宽、末帧 ≥ 1080、每帧 `duration == '0.42s'`、**所有帧旧卡片快照 `opacity < 0.02`**、首帧新页面 `opacity > 0.3`；返回起点 ≥ 1080、最窄 ≤ 1.15×卡片宽、首帧旧快照 `opacity > 0.3`、所有帧卡片快照 `opacity < 0.02`；无 VT / 减少动效照常跳、无 `pageerror`。实测进场 364 → 1131.98、返回 1132 → 364。
- 截图：`design/morph-enter-080.png`、`morph-enter-200.png`、`morph-back-110.png`、`morph-back-240.png`。

## 9. 筛选条件进出详情页（2026-11-18）

点开一条内容再返回，必须回到同一屏：同样的平台 / 关键词 / 排序 / 时间范围，列表还在原来那一行。以前这些活在组件 state 里，跳详情时组件卸载就没了，返回一律是「全部 + 按新鲜度 + 滚到顶」。

### 9.1 筛选条件是 URL 的一部分

- FeedPage 用 useSearchParams 读 p（逗号分隔的平台 id）/ q（关键词）/ sort（freshness 或 engagement）/ range（today 才写）。
- 所有改动走 patch() 写回 URL，setParams(sp, { replace: true })：筛选是同一页上的状态变化，不该每条都堆一条历史记录（否则返回要连按很多次）。
- 点平台胶囊、分段控件、AI 应用条件都走同一个 patch，所以四条路径行为一致；副作用是刷新、分享链接也能复现同一屏。
- 返回按钮不再写死 /：进详情时把 from = location.pathname + location.search 与 fromId 放进 location.state，返回时 navigate(from, { state: { vt: true, back: 1, fromId } })。

### 9.2 三个东西缺一不可

1. feedCache（web/src/api.ts，模块级 Map<cacheKey, FeedResponse>）：返回首帧就用缓存种上 items，否则列表是空的，共享元素找不到落点。cacheKey 用 JSON.stringify([platforms, kind, sort, q, since])，与 URL 参数一一对应。
2. data-vt-item：列表每个单元挂上条目 id，返回时按 fromId 找到那张卡片、给它的 Card 传 vtName 为 of-card。
3. scrollIntoView({ block: "center" })：卡片可能在屏幕外，先把它滚进视野，变形才有起点。缓存没命中时 requestAnimationFrame 再找一次。

### 9.3 滚动归属：谁负责滚，只能有一个

- 进详情：在 runNavTransition 的 apply 回调里 navigate 之后立刻 window.scrollTo({ top: 0 })，在快照之前滚好，详情页不会从列表的滚动位置开始。
- 返回列表：由 FeedPage 的 useLayoutEffect 滚到那张卡片。
- App 里「切页滚到顶」的 effect 必须跳过 state.vt 的跳转。这里踩过一个真坑：那个 effect 是被动 effect、绘制之后才跑，会把 useLayoutEffect 里刚滚好的位置冲回顶部。之前「返回后卡片在视野里」的断言之所以过，只是因为被点的卡本来就在顶部附近。实测修好后，列表滚到 3481px 再点开、返回仍是 3481px，卡片回到 top 346。

### 9.4 可访问性

分段控件（全部/今天、按新鲜度/按热度）与平台胶囊都把选中态暴露成 aria-pressed。既方便读屏，也让行为探针能直接断言状态，不用猜 class。

### 9.5 验收

- tests/test_feed_filters.py（5 项静态）：URL 四个参数读写齐全、replace: true、from 与 fromId 进 state、返回滚到 data-vt-item、App 对 vt 跳转让出滚动、feedCache、aria-pressed。
- probes/check_feed_filters.py（25 项行为，真 Chrome）：点 B 站 → URL 带 p=bilibili → 点开 → 返回 URL / 胶囊 / 命中数 / 卡片落点全保持；浏览器后退键同样保留；深链 ?p=bilibili&q=AI&range=today 三个条件同时生效；排序与 Ctrl 多选往返不丢；空态返回仍是空态；列表滚到 3481px 再点开、返回落点 346px 且不在顶部；全程无 pageerror。
- 截图：design/feed-filter-kept-1.png（筛选后的列表）、-2.png（返回后同一屏）、-3.png（深滚动返回）。

