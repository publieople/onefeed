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

## 7. 平台筛选：按连续段合并的胶囊（2026-11-18）

平台 chips 走过三版：独立药丸（背景硬切）→ 单选胶囊（同一个 `motion.span` 在两项之间滑动）→ 现在的多选分段胶囊。多选之后「一个椭圆到处挪」不再成立：选中的项可能连成一段，也可能分成几段，所以高亮改成**每个连续段一个黑胶囊**。

- 分段判据：按 `PLATFORMS` 顺序扫一遍选中集合，相邻的归为一段；「全部」永远独占一段。
- 视觉：段内是一个整体黑胶囊，段与段之间保持原来的间隙；段内每项保留自己的内边距与圆点，不再加内边框，避免「胶囊里还有缝」。
- 动画：每段一个 `motion.span`，`layoutId={"rail-"+id+"-"+段首 id}` 让段在合并/拆分/拖动时是同一个元素在变形；宽度靠 `layout` 自动补间。新出现的段用 `initial={{opacity: 0, scaleX: .86}}`，`transformOrigin` 朝向已选区域那一侧（新段位于已有段之后 → `left`，之前 → `right`），复用 `SPRING`（stiffness 420 / damping 34 / mass 0.7）；`useReducedMotion()` 退化为 `{duration: 0}`。
- 合并与拆分：往段边上 Ctrl 加一项 → 两段并成一段，宽度朝那一侧长出去；挖掉段中间一项 → 一段劈成两段；Shift 选一段 → 直接生成一整段。
- 交互（照文件管理器）：单击只留这一项；`Ctrl`/`⌘` 点击加/减一项；`Shift` 点击从锚点选一段（`Shift+Ctrl` 并入现有选择）；点「全部」或再点唯一选中项回全部；`←`/`→` 移动焦点并顺带选中。
- 宽度与溢出：外层 `w-fit max-w-full`；内层横向滚动（隐藏滚动条），选中屏幕外的项时 `scrollIntoView({inline: "nearest"})` 带回可视区。

实测（1440×900，`probes/check_tabrail_multi.py` 13 项全过）：B 站 + 小红书（相邻）合成一条，宽度等于两枚胶囊之和（误差 ≤8px）；再 Ctrl 加抖音、掘金，四项仍是一条；Ctrl 挖掉中间的小红书 → 劈成 `[B 站]` 与 `[抖音, 掘金]` 两条；Shift 从 B 站到 V2EX 一次成条；段内 Ctrl 取消掘金 → 劈成 `[B 站, 小红书, 抖音]` 与 `[V2EX]`。`probes/check_tabrail_runs.py` 另测合并宽度、断开与扩散中间帧。截图：`design/tabrail-run-merged.png`（合并成条）、`tabrail-run-split.png`（断开成两条）、`tabrail-run-split-growing.png`（新段长出来的中间帧）、`tabrail-run-shift.png`（Shift 整段）、`tabrail-multi.png`（亮）、`tabrail-multi-dark.png`（暗）。

包体：移掉 Radix 时从 426.67 kB 回落到 402.40 kB；分段胶囊这一版为 407.41 kB（gzip 130.6 kB），多段 `layout` 的代价。

