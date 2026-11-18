# OneFeed 设计评审 · 2026-11-18

评审对象：`E:\Documents\deepseek-harness\default-workspace\onefeed`（web/ 前端，React 18 + Tailwind + framer-motion），运行实例 http://127.0.0.1:8787。
评审方式：源码逐文件读 + 全量 token 扫描 + 真机起服务（8787 直连 dist）在 390/768/1024/1440/1920 五档、亮暗两套主题下截图 + DOM 探针测量 + WCAG 对比度计算 + 焦点/键盘审计。

---

## 一句话结论

底子不差——**等高契约实测成立、平台色克制、暗色是变量而不是补丁**；但设计系统在落地时被「逐页就近实现」侵蚀成了三套并存的方言，而唯一的门禁（check-ui.mjs）恰好只查了 4 条、漏掉字号与圆角这两类最主要的漂移。首屏（Feed）是用户天天看的页面，也恰好是问题最贵的地方。

---

## P0 · 必须改（影响第一眼可信度）

### P0-1 首屏控制区语义塌陷：三个黑块、两个无标签同权胶囊

证据：`web/src/pages/FeedPage.tsx:79-115`
- 第一行给两个 `Seg` 并排：`全部/今天`（时间）与 `按新鲜度/按热度`（排序），**两组都没有组标签、视觉完全同权、各自都有实底选中态**。截图里同时出现两个黑药丸，读者无法判断哪个是时间维度、哪个是排序维度。
- h1 直接复用筛选状态（`text-[15px]`，第 80 行）：`全部内容` / `今天` / `筛选结果`。标题在承担状态机，而状态已经由胶囊表达了一遍。
- 同一屏第三个实底选中块是平台 chip 的「全部 91」（`components/ui/TabRail.tsx:62-68`）。

影响：这是全站第一屏。三个等权的实底块把视觉重心撕成三份，而真正需要被强调的「内容」在下方。
改法：
1. 给两组加小号组标签（`时间` / `排序`，11px uppercase 或前置图标），或把时间收进标题旁的下拉。
2. h1 固定为页面名（`信息流`），条数移到 h1 后（`信息流 · 91 条`），让标题只做定位不做状态。
3. 时间/排序降为「文字级」控件（无实底，选中用 ink 色 + 下划线/字重），全页只保留平台 chip 一处实底选中。

### P0-2 可读性三处硬指标不达标（WCAG AA 需 4.5:1）

实测（相对亮度公式，`contrast.mjs`）：

| 用途 | 前景 / 背景 | 对比度 | 结论 |
|---|---|---|---|
| 11–12px 时间、计数、卡片 footer（`--c-fade`） | #9AA1AB / #FFFFFF | **2.61:1** | 不达标，且是全站最高频的元信息色 |
| 同上，落在 wash 上 | #9AA1AB / #F7F8F9 | **2.45:1** | 更差 |
| 平台徽章白字（B 站） | #FFFFFF / #00A1D6 | **2.97:1** | 11px 白字，最差 |
| 平台徽章（抖音/小红书/掘金/知乎/V2EX） | #FFFFFF / 各自平台色 | 3.66–4.02 | 全部不达标 |
| 卡片描边（卡片与页面同为 paper） | #E9EAEC / #FFFFFF | **1.20:1** | 层级只剩一条几乎看不见的线 |
| 暗色激活项（设置页左栏） | wash #181B20 / paper #0F1115 | **1.09:1** | 看不出选中 |
| 暗色卡片描边 | #2C3038 / #0F1115 | 1.43:1 | 偏弱 |
| 13px 正文（`--c-muted`） | #6B7280 / #FFFFFF | 4.83:1 | 刚过线，无余量 |

影响：整站最常用的两个视觉元素（元信息灰、平台徽章）在亮色下都不合格；卡片靠 1.2:1 的描边区分层级，在低亮度屏/投影仪上会直接糊成一片白。
改法：
1. `--c-fade` 提到 ~#6E747E（对 paper ≈ 4.5:1）；若想保留「更淡」的第三级，只允许它承载非信息性元素（分隔符、禁用态），不允许承载时间/计数。
2. 平台徽章改 `tint/10 底 + tint 深字`（对纸白 ≈ 5:1+），或保留白字但加 12% 黑压边/描边；11px 白字在任何平台色上都不可能达标，这条要正面承认。
3. 卡片边界提到 ~#DFE2E6（1.35:1）并允许卡片用 `shadow-card`；或者反转层级——页面底 wash、卡片底 paper，用明度差而不是描边分卡片（现在两者都是 paper，#FFF 对 #FFF）。

### P0-3 键盘与焦点：全站只有 1 处 focus ring

证据：`grep focus-visible|focus:ring|outline-none` 全仓命中 14 处，其中只有 `web/src/components/ui/TabRail.tsx:58` 真的给了 `focus-visible:ring-2`。
- `web/src/components/Card.tsx:229`：`role="button" tabIndex={0}` 且绑了 Enter/Space，**没有任何 focus-visible 样式**——Tab 到卡片时视觉上毫无变化。
- `FeedPage.tsx:201` 的 `Seg` 是裸 `<button>`，无 `role`/`aria-pressed`、无 `type="button"`、无焦点环。
- 所有输入框是 `outline-none` + `focus:border-*`（1px 边框变色），焦点可见度极低。
- 详情页 lightbox（`ItemPage.tsx:603-610`）无 `role="dialog"`/`aria-modal`、无焦点陷阱、`img` 无 `alt`、无左右切换。
- AI 面板（`AiDock.tsx`）无 `aria-expanded`/`aria-controls`，Esc 不关闭，焦点不转移。

影响：004 规格的 AC-D 写着「键盘可达 Tab/Enter/Space + focus ring」，实际只有 Tab 能走、看不到焦点。这是评委会当场按 Tab 的地方。
改法：全局加一条 `:focus-visible { outline: 2px solid rgb(var(--c-ink) / .55); outline-offset: 2px }`（写在 theme.css，所有组件继承）；Card 换成语义 `<a>` 包一层；Seg 改用 `TabRail`（见 P1-2）。

---

## P1 · 该改（系统性与移动端）

### P1-1 设计系统已失守，且门禁抓不到

量化扫描（`web/src` 全量）：

| 维度 | 规格允许 | 实际 | 越界项 |
|---|---|---|---|
| 字号 | 11/12/13/15/16/17/19/21/38 | 12px(60) 13px(58) 11px(46) 15px(7) 14px(4) 12.5px(3) 19px(3) 17px(2) | **10、14、26、52、12.5**；21 与 38 一次都没用上 |
| 圆角 | card 12 / lg 8 / md 6 / sm 4 | rounded-full(65) lg(44) rounded(23) card(10) | **xl(6)、2xl(1)**；`rounded`=4px 语义不明 |
| 阴影 | shadow-card / shadow-pop | 5 套 | 写死 3 处（AiDock 0.14/0.12、Settings 0.16）+ `shadow-sm` |
| 图标 | 11/14/16 | 9 档 | 10、12、13、15、17、18 |
| 不透明度修饰 | 平台色 4 档 | 19 种（/2 … /95） | — |

根因：规格写在 `specs/004-design-language/spec.md`，但唯一执行机制 `web/scripts/check-ui.mjs`（56 行）只查 4 条：`bg-white`、无遮罩 `text-white`、写死 `rgba(20,2x,2x)` 阴影、`duration: 0.x` 小数，且允许 `ui-lint-ignore` 豁免。**AC-D1 承诺的字号/圆角扫描根本没实现**——于是漂移最严重的两个维度恰好无人看守。

改法（半天，投入产出最高）：把 check-ui.mjs 扩成白名单扫描——
`text-[(d+(.d+)?)px]` → 必须在集合内；`rounded-[a-z0-9[]]+` → 白名单；`shadow-[` → 禁止；`size={d+}` → {11,14,16}；再加一条对比度断言（解析 theme.css 变量，跑上面那张表的 8 组）。

### P1-2 同一个模式，三套实现

| 模式 | 实现 A | 实现 B | 实现 C |
|---|---|---|---|
| Toast | `App.tsx`（motion + `x:"-50%"`） | `SettingsPage.tsx`（motion + `rounded-card`） | `MarketPage.tsx:244`（CSS transform、`rounded-full`、无动效） |
| 单选胶囊 | `ui/TabRail.tsx`（Radix ToggleGroup、有键盘/焦点、共用 layoutId、选中项 scrollIntoView） | `FeedPage.tsx:185` 的 `Seg`（裸 button、无 a11y、弹簧参数 560/40 自造） | — |
| 开关 | `SettingsPage` h-6 w-11 / knob 20px | `AiProviders` h-5 w-9 / knob 16px | — |
| 输入框 | `SettingsPage` h-9 / 13px | `AiProviders` h-8 / 12px mono | — |
| 骨架 | `FeedPage` `animate-pulse` | `MarketPage` 用 `.skeleton` shimmer | — |
| 错误态 | Feed `red-50`（无 dark） | Market `red-50`（无 dark） | Item `amber`（有 dark） |
| 空态 | Feed 大块 420px + 主按钮 | Market 一行灰字 | AI 面板提示 chip |

用户视角就是：同样的事，按钮高矮胖瘦不一样。最刺眼的一对——市场页主按钮 `h-9 rounded-full`（`MarketPage.tsx`），设置页同样的「刷新类」动作是 `h-9 rounded-lg`。
改法：建 `ui/` 目录统一 Button（primary/secondary/ghost/danger × md 36 / lg 40）、Segment（吸收 TabRail 与 Seg）、Toast（唯一实现，挂 portal）、Skeleton、Switch、Field；删掉重复实现。`@radix-ui/react-toggle-group` 已经在依赖里且只在 TabRail 用——`Seg` 直接改成复用 TabRail 即可，零新依赖。

### P1-3 移动端被当成缩小的桌面

实测（390 宽，`shot2.html` 真机渲染）：
- **设置页移动端没有分区导航**：左栏 `hidden lg:block`（`SettingsPage.tsx:261`），5 个长 section 只能一条道滚到底。
- 顶栏品牌 + 4 个 36px 图标按钮塞满；刷新/主题/市场/设置四个不同权限、不同频次的操作同权并排，移动端没有折叠菜单。
- 触控目标：平台 chip 约 25px 高、Seg 约 20px、图标按钮 36px——全部低于 44px 的移动端建议下限。
- 刷新进度文字 `hidden md:block`：移动端点刷新没有任何进度反馈。
- 平台 chip 条装在全宽 `rounded-full border` 外框里，390 下被裁切且无渐隐/箭头提示还有更多（`TabRail.tsx:40` 外框 + 内层 `overflow-x-auto`）。
- AI 胶囊固定在底部，滚动时压住卡片标题与 footer（作者、点赞数）。
- 顶部摘要 4 行被截成「…挣到钱的 AI 公。」——断句在句中被截断。

改法：设置页移动端改为顶部横向 TabRail（同一组件，免新造）+ 每 section 折叠；顶栏移动端收成「菜单 + 主题」两个按钮，市场/设置进抽屉；chip 条加左右渐隐遮罩；进度改到刷新图标本身（转圈）而不是文字。

### P1-4 详情页的阅读体验

- 正文 `text-[14px] leading-[1.9]`，容器 `max-w-[860px]`（`ItemPage.tsx:383/470/474`）→ 约 **55 汉字/行**，中文舒适区是 30–40，长文读起来会丢行。
- h1 `text-[26px]`（`ItemPage.tsx:402`）是自造档：比规格的 21px 大 24%，同时把 15px 的页面标题衬得更像脚注——**全站没有稳定的标题梯度**（15 → 16 → 26，中间没有 h2/h3）。
- 正文链接写死 `[&_a]:text-[#1E80FF]`（掘金蓝）：在小红书/B 站/知乎的内容里，链接是掘金色。
- 顶部一行三种形状：平台徽章药丸（full）+ kind 标签（`rounded`=4px）+ 纯文字时长，形状语义互相抵消。
- 统计卡 `min-w-[86px]`×4，390 下换行成 3+1，第四张「分享」独占一行的孤行。
- 「去 X 看原帖」在页面最底部（`ItemPage.tsx:584`），而播放器/媒体在顶部——想跳原站得滚到底。

改法：正文改 `max-w-[68ch]`（或 15px/1.75）+ 链接色用 `platform(p.platform).tint`；h1 回到 21–24 之间并给 h2/h3 建立梯度；kind 标签改药丸或改成前置小 icon + 文字，别和徽章拼形状；统计卡改 `grid grid-cols-2 sm:grid-cols-4` 避免孤行；「去原帖」复制链接并提到标题行右侧（sticky 或首屏内）。

### P1-5 市场页：把开发者面板摆成了产品页

- 每张卡都挂「✓ 已安装」——全部已装时是零信息徽章。
- 「卸载」（破坏性）与「刷新目录」（中性）同权重、同色描边。
- 卡片正文是实现细节：`浏览器回放，不碰签名`、`宿主注入 cookie`、`browser`/`http`/`cli` 这些 kind 标签——目标用户不需要知道。
- 页脚直接暴露 registry URL：`https://cdn.jsdelivr.net/gh/publieople/onefeed-plugins@main/registry.json（本地缓存）`。
- 空态只有一行 mt-16 灰字，没有图形或引导。
- 卡片 `p-5`（20px）与规格「卡片内边距固定 12px」冲突，右侧操作区与正文之间留出大片空白（2 列 × 1280）。

改法：状态只标异常（需登录/不可用），默认不标；卸载改 danger 幽灵按钮并二次确认；描述改用户语言（「读取你已登录的推荐流」）；registry URL 收进「开发者信息」折叠；卡片内边距回 12–16px。

---

## P2 · 快改清单（每条都是独立小 PR）

1. 设置页「运行状态」是 label 左、value 甩到 800px 卡片右端的键值表（`SettingsPage.tsx`）——四组值交错，视线要走 Z 字。改 `grid grid-cols-[88px_1fr]`，value 紧随 label。
2. section 右上 28px 圆圈 chevron 看着像按钮，实际是折叠指示（整行才是触发区）——要么把 chevron 去掉，要么让它自己也可点。
3. 「清除所有 key」在 0 个模型时仍是可用样式，缺 disabled 态。
4. Feed 骨架 `min-h-[340px]`、真实卡 380.6px → 加载完成会跳一下。
5. `.nav-active` 的注释写着「一条贴着实色的短竖线」（`theme.css:195`），实现只有 color + background——**注释承诺的竖线没写**。
6. 暗色下三处错误框仍是 `red-50`/`red-200`（`FeedPage.tsx:126`、`MarketPage.tsx:144`、`SettingsPage.tsx:34`）→ 暗色里出现一块刺眼浅红。
7. `rounded-xl` 残留 6 处（`AiProviders.tsx:86`、`ItemPage.tsx:433/435` 等）——规格明令禁止。
8. `ItemPage` 两个「更多评论」按钮 `text-[12.5px]`（0.5px 步进，规格禁止）。
9. `CommentBody.tsx:7` 写死 `#6b7280` 做头像底色（既不是 token 也不是平台色）。
10. 大屏 1440：容器 1180 左右各留 ~106px，3 列卡片仅 364px 宽 → 要么 4 列，要么容器放到 1320。
11. 「库里共 91 条；主要来自 知乎热榜 24 条…同一件事最多有 2 个平台在讲…」是数据自检句，放在首屏正文位；「筛选出 N 条，共 M 条命中」是工程口径。
12. 摘要里直接露裸 URL（`https://space.bilibili.com/4096581?...`）——卡片摘要应做 URL 折叠。
13. `TabRail` 选中块用 `shadow-sm`（不在 shadow-card/pop 两个 token 里）。

---

## 做得对的地方（别在重构里弄丢）

1. **等高契约真的成立**：五档视口实测同视口卡片高度唯一值（368.3 / 372.8 / 444.8 / 380.6 / 380.6），没有横向溢出。这是最难的一条，很多成熟产品都做不到。
2. 平台色只做点、边、渐变，不铺卡片底——五平台并列时页面没有变成调色盘。
3. 暗色是 CSS 变量而不是覆盖式补丁，切主题无闪白（首帧内联脚本），这层底子扎实。
4. `ui/TabRail.tsx` 是这仓里最专业的组件：Radix ToggleGroup（自带 roving focus）+ 共用 `layoutId` 滑块 + 选中项 `scrollIntoView` 带进视野 + `useReducedMotion` 降级。`Seg` 应该向它投降，而不是反过来。
5. 动效克制：`rise` 34ms 步进、`reduced-motion` 全量降级、瞬时状态不占文档流。

---

## 修复路线（按投入产出）

**Step 1 · 半天，纯护栏**：check-ui.mjs 扩成白名单 + 对比度断言。做完立刻能扫出本报告 P1-1 的全部越界项，且以后进不来。

**Step 2 · 1–2 天，抽组件**：theme.css 加 `--c-fade-strong`（承载信息）与 `--c-line-strong`；建 `ui/Button|Segment|Toast|Skeleton|Switch|Field`；`Seg` 合并进 TabRail；三处 Toast 合一。改完 P1-2、P2-7/8/13 自动消失。

**Step 3 · 2–3 天，页面**：Feed 控制区重排 + 标题层级（P0-1）；Settings 移动端导航（P1-3）；Item 排版与链接色（P1-4）；Market 语义与文案（P1-5）。

**Step 4 · 可选，A11y 收口**：全局 focus-visible（P0-3）、Card 语义、lightbox `role=dialog` + 焦点陷阱 + 左右切换、AI 面板 aria + Esc。

**验收口径（三条可复测的断言）**
1. 对比度脚本：所有「文字/背景」对 ≥4.5:1（大字 ≥3:1），0 例外。
2. 字号/圆角/阴影/图标扫描：越界 0 处。
3. Tab 走完 Feed → Item → Settings 三屏，每一步都有可见焦点，Enter 可触发。

---

## 附：复现方式

- 对比度：`node contrast.mjs`（本仓根目录，读上下两张表的值）。
- 真机截图：8787 已直接托管 `web/dist`，`/shot2.html?w=390&h=800&path=/settings&theme=light` 出移动端长图；桌面端 1280 直连即可（用 iframe + `transform:scale` 会拿到空白帧，已验证）。
- 五档测量：`/probe.html` iframe 真机渲染后读 DOM（卡片高度、h1 字号、align-items、顶栏高度）。
