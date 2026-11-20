# onefeed 交互与性能复评（2026-11-20 第二轮）

范围：本轮改动 `917ae78` 左栏宽度补间、`2f7e0fb` Lenis + 右栏宽度补间、`bdef778` 侧栏滚轮缓动、`0ad0050` 上一轮评审修复。
口径：Chrome 1440×900 / 1600×900 headless，真实数据 961 条（8799 demo），补图库 8801；rAF 逐帧采样 + PerformanceObserver(longtask) + CDP Performance.getMetrics；每个动作真鼠标（CDP 直发），不再混用 Playwright 的 scroll_into_view 超时。
复现资产：`probes/review2_left_idle.py`、`probes/review2_grid_pause2.py`、`probes/review2_edge_modal.py`、`probes/review2_pause_clean.py`、`probes/review2_scroll_owner.py`、`probes/probe_lenis_rail.py`；截图 `.onefeed/shots/rail-*.png`。

## 结论速览

1. 本轮新引入的 Lenis 在空闲时持续占用主线程：2 个实例时 rAF 回调 149–151 次/秒、CPU 6.1–7.6%；reduce 下（0 实例）0 次、0.4–1.2%。这是本轮最值得先修的一条。
2. 栏宽补间仍然是「分档跳」而不是逐帧：左栏收起 4–8 档、单帧最大 90–99px；右栏打开 8 档、单帧 49px，打开时 80ms 帧 + 54ms 长任务。补间期间网格列数还会在一次采样里从 3 列翻到 4 列，卡片宽度出现「先涨后缩」过冲（370→426→317）。
3. 侧栏惯性本身达标：滚轮 3×400 连滚 118 帧、最大帧 26.2ms、0 jank，落点精确到底。
4. 侧栏到底后滚轮被吃掉，不交还页面；确认框/灯箱打开时背景页面仍能被滚走（650px / 175px）。
5. 流式输出期间没有掉帧（10s 748 帧、p95 13.5ms、0 长任务），Lenis 的 120ms 全量扫描目前还不是瓶颈，但属可预测的固定成本。
6. 仓库测试套件在 main 上是红的：`tests/test_api.py:80` 断言「feed 首条按时间倒序」，而 `store.page(mix=True)` 早已改成按平台轮转交错。

## 代码问题

### C-01 默认排序断言与实现冲突，main 上测试套件红
- `tests/test_api.py:80`：`check(feed["items"][0]["id"].endswith(":0"), "feed 默认按时间倒序")`。
- 实现：`onefeed/store.py:435-457` 的 `mix` 分支按「本平台内第几名 + rot」交错铺开，首条不再等于全局最新。
- 交错由 `8b217c3` 引入，`tests/test_api.py` 最后改动是 `4cb300d`，没人跑 `run_all` 所以一直没暴露。复现：`uv run python tests/test_api.py` → AssertionError；`uv run python tests/run_all.py` → 23 套通过、1 套失败。

### C-02 每个滚动容器一条常驻 rAF（Lenis autoRaf）
- `web/src/motion/useSmoothWheelScroll.ts:41-52`：每个 `[data-smooth-scroll]` 容器 `new Lenis({ ..., autoRaf: true })`。
- 实测实例数：首页 2（`.lenis` ×2），详情页 + AI 右栏 3。
- 空闲 3s：默认 450–454 次 rAF 回调（149–151/s）、TaskDuration 185–229ms（6.1–7.6%）；`emulate_media(reduced_motion="reduce")` 重载后 0 次、12–37ms（0.4–1.2%）。
- Lenis 支持 `autoRaf: false` + 自建单一循环，多实例共用一条 rAF 即可；本页最多 3 个实例，等于白烧 2/3。

### C-03 refresh 每 120ms 全文档扫描 + 逐实例 resize
- `useSmoothWheelScroll.ts:64-82`：`refresh()` 先 `scan(document)`（全文档 `querySelectorAll`），再 80ms 后对每个实例 `lenis.resize()`（读 scrollHeight 会强制回流）。
- 流式输出时 DOM 每帧变化，120ms 合并一次仍会持续触发。
- 实测 10s 流式窗口 748 帧、p95 13.5ms、0 长任务 —— 目前不慢，但 MutationObserver 已给到 `addedNodes`，只扫新增子树、只在盒子尺寸变化时 resize 是免费的优化。

### C-04 暂停用模块级布尔，嵌套模态会提前恢复
- `useSmoothWheelScroll.ts:25` `let paused = false`；`:113-122` 卸载时无条件 `paused = false; start()`。
- 两个模态同时开着时，先关的那个会把后关的那个的暂停也解除。当前灯箱只在详情页、确认框在设置/市场，天然不共存，属潜在缺陷；改计数器或 Set 即可。
- 单模态路径实测有效：确认框打开时侧栏 345→345（不动）；灯箱打开时同理；`[` 不改栏宽、`?` 不弹帮助（上一轮 C-02 修复生效）。

### C-05 惯性未收敛时外部 scrollTop 会被拉回
- 实测：侧栏滚到 345 后 `scrollTop = 0`，900ms 后又是 345（Lenis 的 target 仍指向惯性终点）。
- `web/src/agent/AgentThread.tsx:19-20` 已经改用 `scrollTo({ behavior: "instant" })`，所以吸底本身安全；风险留给以后任何直接赋 `scrollTop` 的代码（保存/撤销回滚、锚点修正）。

### C-06 补间没有「列数门控」，中途换列
- `web/src/layout/useGridCols.ts:83-98` 用 ResizeObserver 逐帧量内容宽度，`:106` 直接按当前宽度算 `cols`。
- 实测收起：`3c/370.7 → 3c/426.4（一帧）→ 4c/317`；展开：`4c/317 → 4c/285.7 → 3c/370.7`。列数在补间中途翻转，卡片宽度先过冲再回落。

### C-07 右栏打开与关闭的代价不对称
- `web/src/layout/Shell.tsx:181-198` 右栏用 `animate={{ width: RIGHT_W }}` 补间；打开时插入 320px 内容，关闭时只是移除。
- 实测 1600：打开 max 80.2ms / 54ms 长任务 / 单帧 49px；关闭 max 31ms / 0 长任务。

### C-08 文档里的补间数字偏乐观
- `docs/left-rail-tween-2026-11-20.md` 记录收起 p95 47 / max 134 / 首次长任务 127ms、展开「长任务 0」。
- 本轮 3 轮复测：收起 max 146.7 / 93.4 / 80.0ms，长任务 141 / 73 / 0ms；展开 max 106.8 / 93.5 / 93.4ms，长任务 57 / 54 / 51+50ms。展开也有长任务，只有第 2 轮以后才接近文档口径。

## 交互问题

### I-01 补间期间两套侧栏内容同时可见
收起时宽度还在 240→64 的途中，`.side-layer` 的交叉淡入（180ms）已经开跑，图标层先出现在仍然很宽的栏里。截图 `.onefeed/shots/rail-mid110.png` 里栏已收到 64px 但顶部「收起」按钮仍在 200px 位置残留一帧；文档自述双层可见 60–100ms，实际观感是「两栏叠了一下」。

### I-02 收起左栏时卡片会「先胖再瘦」
370.7 → 426.4 → 317 的三步发生在 260ms 内，用户看到的是卡片先被拉宽、再被挤窄。这是 C-06 的交互面。

### I-03 右栏打开比关闭明显更「拽」
打开时内容列 3 列卡宽 424→317 逐帧重排，80ms 帧；关闭 31ms。同一个控件两个方向手感不一致。

### I-04 滚轮在侧栏底部被吃掉
首页页面可滚（scrollHeight 2816），指针停在左栏会话列表底部（568/568）继续滚 600px，`window.scrollY` 仍为 0。Lenis `overscroll: false` 在边界处仍然 preventDefault，滚轮像被「顶住」，必须把指针移回正文。

### I-05 弹层不锁背景滚动
- 确认框（设置页「清除所有 key」）打开时滚轮落在遮罩上：页面 614 → 1264。
- 灯箱打开时 body `overflow: hidden`，但滚轮仍把页面从 0 推到 175（html 还能滚）。
背景被推走后关掉弹层，用户已经不在原来的位置。

## 性能问题（实测）

| 操作 | 采样 | 帧 p50/p95/max | jank / >60ms | 长任务 |
| --- | --- | --- | --- | --- |
| 左栏收起（首轮） | 24 帧 / 827ms | 13.5 / 93.3 / 213.5ms | 6 / 4 | 2 条，最高 186ms |
| 左栏收起（第 3 轮） | 43 帧 / 774ms | 13.4 / 40.3 / 53.4ms | 5 / 0 | 0 |
| 左栏展开（首轮） | 34 帧 / 787ms | 13.3 / 93.5 / 213.5ms | 4 / 2 | 1 条 215ms |
| 左栏展开（第 3 轮） | 45 帧 / 774ms | 13.3 / 40.0 / 53.6ms | 4 / 0 | 0 |
| 右栏打开（1600） | 61 帧 / 1027ms | 13.4 / 53.1 / 80.2ms | 5 / 1 | 1 条 54ms |
| 右栏关闭（1600） | 64 帧 | — / — / 31ms | 0 / 0 | 0 |
| 侧栏惯性滚（3×400） | 118 帧 / 1573ms | — / — / 26.2ms | 0 / 0 | 0 |
| 流式 10s 窗口 | 748 帧 | 13.3 / 13.5 / 66.8ms | 1 / 1 | 0 |
| 空闲 3s（Lenis 开） | — | TaskDuration 185–229ms | — | CPU 6.1–7.6%，rAF 149–151/s |
| 空闲 3s（reduce） | — | TaskDuration 12–37ms | — | CPU 0.4–1.2%，rAF 0/s |

- 包体：`web/dist/assets/index-CR-UP0mD.js` 505.2 kB raw / 160.2 kB gzip；上一轮基线 491.16 kB / 158.56 kB，Lenis 约 +14 kB raw / +1.6 kB gzip。
- 补间实测宽度只有 4–8 个不同值（260ms 应约 16 帧），长帧把中间档吃掉，肉眼就是台阶。

## 改进建议

### P1（本轮就该做）
1. **Lenis 改共享 rAF**：`autoRaf: false`，一个 `requestAnimationFrame` 里遍历 `instances` 调 `lenis.raf(t)`。验收：首页空闲 rAF 回调 ≈60/s（而非 150/s），CPU ≤2%。
2. **补间期间冻结列数/卡宽**：`useGridCols` 增加「animating」门控，补间期间用目标宽度算 cols 并钉住 `gridTemplateColumns`，结束时一次性重算。验收：收起/展开各 5 次，卡宽 distinct ≤2、无 >60ms 帧、无长任务；右栏打开 max ≤40ms。
3. **右栏打开跟上关闭的手感**：先插栏（width 立即到位）再让内容列 120ms 内淡入，或同样冻结列数；目标 max ≤40ms、0 长任务。
4. **模态锁背景**：打开确认框/灯箱时给 `html` 加 `overflow: hidden` + `scrollbar-gutter: stable`（或在遮罩上 `preventDefault` wheel）。验收：弹层打开时滚轮 600px，`window.scrollY` 不变。
5. **侧栏到底交还滚轮**：Lenis 在边界不 preventDefault（`overscroll: true` 或边界处手动放行）。验收：列表到底后继续滚 400px，页面滚 400px。
6. **修 `tests/test_api.py:80`**，并把 `tests/run_all.py` 接进 preflight 或 CI —— 现在 24 套里 1 套红着没人知道。

### P2（顺手）
7. refresh 增量扫描：只处理 `addedNodes`，resize 只在容器尺寸变化（或首挂载）时调。
8. 暂停改计数/Set，避免嵌套模态提前恢复。
9. 补间曲线统一：CSS 侧 `.shell-col` 的 `cubic-bezier(0.22,1.24,0.36,1)` 已不参与宽度（`transition: none`），但别处仍留着带过冲的曲线；全站 EASE 是 `[0.22,1,0.36,1]`，与手机示范类 skill 的弹性入场 `cubic-bezier(.34,1.56,.64,1)` 比，onefeed 的过冲更小、更克制，建议保持一种曲线，不要两套。
10. 列表 stagger 目前 `Math.min(index,11)*22ms`（`web/src/pages/FeedPage.tsx:439`），比示范类 skill 常用的 60–80ms 更密；卡片数多时同帧压力更大，可考虑改成 6 张之后统一延迟。

## 本轮实际用到的工具

| 工具 | 用在哪 | 结论来源 |
| --- | --- | --- |
| `browser_navigate` / `browser_snapshot` | 打开 8799、枚举 124 个可交互元素、确认按钮名与 28×28 / 36×36 小目标 | 选择器与坐标 |
| `browser_console` | 检查运行时错误/告警 | 0 条 |
| Playwright + CDP（`probes/*.py`） | rAF 逐帧采样、PerformanceObserver longtask、`Performance.getMetrics` 取 TaskDuration、`emulate_media(reduce)` A/B、`mouse.wheel` 真滚轮 | 全部帧数/长任务/CPU |
| Playwright clip 截图 | 补间中间态（110ms / 230ms） | 截图在 110ms 时已基本收完，抓不到中间档，结论改由帧采样给出 |
| `phone-ui-demos` skill | 取「弹性入场 cubic-bezier(.34,1.56,.64,1)、列表 stagger 60–80ms」作手感参照 | 建议 9/10 |
| `swiss-shot-demos` skill | 取「快进快停、禁弹跳闪烁」作动效取向参照 | 建议 9 |
| `node web/scripts/check-ui.mjs` | UI 门禁 | OK：没有违规 |
| `uv run python tests/run_all.py` | 全量回归 | 23 通过 / `test_api` 失败 |

未采用的：`stacked-data-cards`、`card-theater`、`video-shot* / promo-video-maker` 等产物是静态 HTML/视频，不能直接用于 React 组件；`dsh-smooth-stream` 面向宿主聊天流式渲染，onefeed 有自研流式，没接。

## 未覆盖

- Safari / Firefox、真实触控板（Windows 精密触控板会连发小 delta，Lenis 的 lerp 可能叠加成「滑过头」）。
- 窄屏 <960 两栏都不渲染，未复测抽屉打开时的列数变化。
- 灯箱多图真实数据（用 8801 补图库验证 pause，未做 10 张以上的连续翻页压测）。
- Agent 一轮 20–37s 的整段流式（本轮只取前 10s 窗口）。
