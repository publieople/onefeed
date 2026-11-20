# 设计类工具清点与 onefeed 适用性评估

> 采集日期 2026-11-20。清点口径：desktop profile 已装 24 个 bundle（`~/.dsh/profiles/desktop/package.json`）+ 本机 `~/.dsh/skills` 65 个 skill + OpenViking `viking://agent/skills`。下文只保留与「前端 UI / 动效 / 视觉产出」相关者。

## 一、先给结论

1. **真正能直接提升 onefeed 交互性能的工具只有一类：浏览器测量工具链**（内置 `browser_*` CDP 工具 + 仓库里已有的 `probes/ops_frames.py`）。其余设计类 skill 的产物是**静态 HTML / 视频 / 图片**，不能直接改 React 组件。
2. 设计类 skill 能迁移过来的是**设计判断与节奏参数**（easing、时长表、字体阶梯、对比度、点击目标尺寸），不是代码。直接把它们的产物搬进 onefeed 会引入第二套设计语言 —— 这正是 `docs/design-review-2026-11-18.md` 里「设计系统被逐页就近实现侵蚀成三套方言」的同一个病根。
3. 本轮 onefeed 已落地 Lenis 惯性滚动与左右栏宽度补间（`bdef778` / `2f7e0fb` / `917ae78`），「滚动不像惯性」「栏宽硬切」两个手感问题已闭环，工具选型应转向**验证与回归**，而不是再引入动画库。

## 二、插件（宿主 UI 类，共 7 个）

| 插件 | 作用 | 对 onefeed 的适用场景 | 结论 / 优先级 |
| --- | --- | --- | --- |
| `dsh-smooth-stream` | DSH 回复的流式渲染与顺滑滚动（Markdown/代码/表格） | **取实现思路**：帧批处理、避免 layout thrash、按 rAF 合并 DOM 写入。onefeed 的 `AgentProvider.tsx` 每事件整数组复制 `setLive` 可照此收敛 | P1（方法参考，不装到产品） |
| `dsh-guizang-design` | 网页 PPT / 图文卡片 / 网页排版 / 去 AI 味四 skill + 作品库 | **取设计系统纪律**：字号阶梯、间距、对比度、版式约束；用来收敛 onefeed 的三套设计方言 | P1（方法层，产物不落地） |
| `dsh-interim-narration` | 让 agent 每轮先讲理解与计划、工具间写过程叙述 | **直接对应** Agent 面板 8.4s→21.4s 零变化的静默问题：把「边做边说」的节奏搬进 `AgentThread` | P1（交互模式参考） |
| `dsh-whale-widget` | 带弹簧/吸附/音效的余额挂件 | 微交互实现参考（吸附、翻转、逐行样式） | P2 |
| `dsh-better-sidebar` | 文件树/编辑器/任务/侧聊一体的侧栏 | 面板布局与分栏动效参考 | P2 |
| `@linxin666/dsh-web-all` | skin-center / pet / web-ui-settings 聚合 | 主题切换与皮肤系统参考（onefeed 已有 theme-vt clip-path） | P2，价值低 |
| `dsh-media-desk` | 灵感→口播脚本/标题/封面/配图/黑白线稿分镜 | 只在做宣传物料时用 | P3 |

## 三、Skill（设计/视觉类，共 29 个）

### A. 与「交互与动效」有真实交集（6 个）

| Skill | 产物 | 对 onefeed 的用法 | 优先级 |
| --- | --- | --- | --- |
| `swiss-shot-demos` | 瑞士风图表分镜 HTML | **取节奏表**：一镜一时长、图表入场级联的毫秒编排，可反推 onefeed 的 stagger 与 delay 上限 | P2 |
| `video-shot-demos` | 每镜头一个 HTML 的演示动画 | 同上，取转场与音画同步的时间基准 | P2 |
| `stacked-data-cards` | 叠放数据论点卡 + 数字滚动/环形仪表 | 详情页统计数字的滚动动画可复用其实现 | P2 |
| `phone-ui-demos` | 手机系统 UI 风格电影化演示 | 390 宽下的手势、底部抽屉、点击目标尺寸参考 | P2 |
| `card-theater` | 3D 卡片轮播/滚动翻页 | 手势驱动与 3D 层叠参考（onefeed 暂无此需求） | P3 |
| `win11-ui-demos` | Win11 系统 UI 仿真 | 系统级动效纪律参考，与 Web 产品距离远 | P3 |

### B. 设计系统 / 排版 / 文案（4 个）

`guizang-page-skill`（P1，唯一的「精排单页 HTML」，取字体阶梯与栅格纪律）、`guizang-ppt-skill`（P3，只用于评审汇报 deck）、`guizang-social-card-skill`（P3，发布卡片）、`guizang-voice`（P3，语气档案）、`humanizer` / `humanizer-zh`（P3，只用于空态/提示文案去 AI 味）。

### C. 图表 / 视频 / 音频物料（仅做交付物，不改产品）

`dynamic-archify`（架构图）、`flowchart`（流程图）、`network-protocol-viz`（协议动画）、`ppt-animation`（翻页 PPT）、`ppt-master`（PPTX）、`video-shotcraft`（Remotion 宣传片）、`promo-video-maker`（4K 宣传片）、`vocaloid-style-mv`（MV）、`audio-mixing` / `procedural-audio` / `sfx-sources`（音效）、`scholar-notes`（手写笔记页）、`wechat-share`（群消息）。**对 onefeed 交互零增益，列为 P3 或不用。**

### D. 过程方法类（不是设计工具但影响设计评审质量）

`grilling` / `grill-me`（对方案做压力测试，适合评审前自检）、`i-have-adhd`（输出结构）、`find-skills`（发现新工具）。

## 四、优先级排序（按「对 onefeed 前端交互的真实杠杆」）

- **P0 · 每轮评审默认工具链**：内置 `browser_navigate/snapshot/click/screenshot/console/network` + `probes/ops_frames.py`（rAF 逐帧 + longtask + MutationObserver 首动）。理由：所有手感判断都必须有帧数据，否则只能靠猜。
- **P1 · 直接改产品（4 项）**：`dsh-smooth-stream`（流式渲染收敛）→ `dsh-interim-narration`（静默段反馈）→ `guizang-page-skill`（设计系统收敛）→ 继续用 `probes/` 做回归门禁。
- **P2 · 取参数与组件参考（6 项）**：`swiss-shot-demos`、`video-shot-demos`、`stacked-data-cards`、`phone-ui-demos`、`dsh-whale-widget`、`dsh-better-sidebar`。
- **P3 · 只在做物料时用**：`guizang-ppt-skill`、`dsh-media-desk`、`dynamic-archify`、`flowchart`、`humanizer-zh`、`card-theater`、`win11-ui-demos`。
- **不推荐用于本项目**：`video-shotcraft`、`promo-video-maker`、`vocaloid-style-mv`、音频三件套、`scholar-notes`、`ppt-master`、`network-protocol-viz`、`guizang-social-card-skill`、`wechat-share`。

## 五、映射到当前未修的交互问题

| 剩余问题 | 用哪个工具验证/改进 |
| --- | --- |
| Agent 流式事件整数组复制、13s 静默 | `dsh-smooth-stream` 的 rAF 批处理 + `dsh-interim-narration` 的叙述节奏 |
| toast 双定时器互不取消（`App.tsx:71/158`） | `browser_console` 打点 + `probes/ops_behavior` |
| 灯箱无 `role=dialog`、插件开关无 aria | `browser_snapshot` 语义检查；方法参考 `guizang-page-skill` 的可访问性段落 |
| 设置页 flash 与保存条同槽 | `browser_screenshot` 定点截图比对 |
| 动画节奏不统一（DUR.page 0.26 vs D.page 0.42） | `swiss-shot-demos` / `video-shot-demos` 的时长表做外部校准 |
