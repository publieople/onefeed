# 侧栏开合不再改动信息流列数（2026-11-20 夜）

## 病

点一下左栏收放、或开右栏，整屏卡片的换行位置跟着变：收左栏时 3 列 370px 一下变成 4 列 317px，卡片先胖再瘦、整页重排一次。用户的话是「展开左右侧栏都会导致主页面信息流列数自动变动、造成跳变」。

根因在列数的输入源：`web/src/layout/useGridCols.ts` 原本用 `ResizeObserver` 盯网格自身宽度，侧栏一推内容列就变窄/变宽，列数跟着重算。上一版的补丁（`gridFreeze.ts`）只在补间 340ms 内把目标宽度冻住 —— 动画结束照样按新宽度算，等于只把跳变推迟了 300ms。

## 改法

一句话：**列数只由窗口宽度决定，侧栏开合不参与计算。**

- `web/src/layout/useGridCols.ts`
  - 删掉 `ResizeObserver`（这是关键的一刀）。宽度只在两个时机重新量：`window` 的 `resize`（rAF 合并）和挂载后的 `SETTLE_MS = 420` 一次补量（右栏默认展开时开栏动画落定后取真实宽度，避免按全宽算列）。
  - 计算回到纯函数：`maxFit = maxFitCols(width)`，`cols = choice === "auto" ? Math.min(autoColsFor(width), maxFit) : Math.min(choice, maxFit)`。
- `web/src/layout/Shell.tsx`：删掉 `prevWidths` + `freezeGridWidth(base - dLeft - dRight, ...)` 那段，只留一行注释说明列数不在这里干预。
- `web/src/layout/gridFreeze.ts`：整份删除。
- 卡片本身仍随列宽连续变化（网格是 `repeat(N, minmax(0, 1fr))`），所以侧栏动画期间卡片会平滑变胖变瘦，但**换行位置不动**。

## 实测

Chrome headless，1440×900，961 条真实数据，`probes/probe_grid_stable.py` 在每次开合全程逐帧读 `gridTemplateColumns` 与首张卡宽度：

| 操作 | 起始列数 | 过程中出现过的列数 | 结束列数 | 首张卡宽度 | 结果 |
| --- | --- | --- | --- | --- | --- |
| 收左栏 | 3 | `[3]` | 3 | 370.7 → 429.3 | 通过（67 帧） |
| 展开左栏 | 3 | `[3]` | 3 | 370.7 → 429.3 | 通过（70 帧） |
| 开右栏 | 3 | `[3]` | 3 | 370.3 → 264.0 | 通过（62 帧） |
| 关右栏 | 3 | `[3]` | 3 | 264.0 → 370.7 | 通过（67 帧） |

「卡片宽度确实变了」这条判据是必须的：只验列数会漏掉「侧栏根本没动」这种假通过。

`probes/probe_grid_resize.py` 验另一头 —— 稳定不等于冻死：

| 窗口宽度 | 列数 | 首张卡 | 左栏 |
| --- | --- | --- | --- |
| 1440 | 3 | 370.7 | 240 |
| 1100 | 2 | 396.0 | 240 |
| 900 | 2 | 416.0 | 0（两栏都隐藏） |
| 1600 | 3 | 424.0 | 240 |
| 1100 下展开左栏 | 2 → 2 | 396 → 484 | 64 → 240 |

窄屏那条同样全程只见 `[2]`，卡片从 396 撑到 484，说明列数稳定与内容列真的在动两者同时成立。

## 代价与边界

- `SETTLE_MS` 是一次性补量而不是持续观察：如果将来有别的浮层在挂载 420ms 之后把内容列永久变窄，列数不会自动跟上。当前只有左右栏会改内容列宽，且都在这个窗口内。
- 侧栏补间期间卡片宽度是连续变化的，字号的容器查询断点在 250px/600px 两档，370→429 这一段不跨档，所以不会每帧换字号（这条在 `tests/test_grid_cols.py::test_breakpoints_avoid_the_width_the_left_rail_sweeps_through` 里钉着）。
- 未测 Firefox / Safari；窄屏只测到 900（再窄两栏都不渲染）。

## 守门

- `tests/test_grid_cols.py::test_column_count_follows_window_width_not_side_rails`：断言 `new ResizeObserver` **不**出现、有 `window.addEventListener("resize")`、有 `el.clientWidth`。
- `tests/test_motion_coverage.py::test_grid_cols_only_follow_window_width`：断言无 `new ResizeObserver`、有 `SETTLE_MS`、无 `useGridFreeze`/`frozen`、Shell 不含 `freezeGridWidth`/`gridFreeze`、`gridFreeze.ts` 文件不存在。
- 门禁：`pwsh scripts/preflight.ps1`（pytest 115 → run_all 26 项 → check-ui → build）。
