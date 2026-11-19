# 左栏收放 · 底部唤起器 · 无限预取（2026-11-19）

本轮处理四件事：左栏展开变成浮层、底部胶囊一直挡内容、缺回顶入口、刷到底才开始取下一页。

## 1. 左栏：只在栅格里收放，不再有浮层

### 现象与根因
- 1280 上点图标轨的「展开」，出来的是 `fixed inset-0` 全屏层：288 抽屉压在页面左边，
  背后一层 `bg-solid/20` 遮罩，Esc 才关得掉。用户原话是「挡住整个页面，破坏沉浸感」。
- 根因在 `web/src/layout/useShell.ts`：`toggleLeft` 在 <1440 时走 `setLeftDrawer(true)`，
  而 `web/src/layout/Shell.tsx` 里那层浮层就是它的落点。也就是说「展开」和「变宽」被拆成了两套东西。

### 改法
- 删掉 `leftDrawer` 整套机制：state、跨断点重置 effect、浮层 DOM、dialog 作用域与 Esc 绑定。
- 左栏只剩三档，全部待在栅格里：`width >= 1024 ? (expanded ? "full" : "rail") : "hidden"`；
  `toggleLeft` 只翻转 `expanded` 并写 `localStorage: onefeed.shell.left`。
- 图标轨上的展开按钮（`onExpand`）和 `[` 键走同一个 `toggleLeft`：点一下就是这一列从 64 变宽到 288，
  内容列由 flex 自动让位。
- 默认态：`readFlag(LEFT_KEY, clientWidth >= 1440)` —— 宽屏默认展开，1280 上默认图标轨，
  先给内容列留地方。

### 实测（Chrome 1280×860）
| 状态 | 左栏宽 | 主列宽 | 浮层 |
| --- | --- | --- | --- |
| 初始（图标轨） | 64 | 1156 | 0 |
| 点展开 | 288 | 932 | 0 |
| 再收起 | 64 | — | 0 |

`body` 的 `overflow` 全程是 `visible`（没有被锁滚动）；1440 视口下默认 288；
900 视口下没有左栏，按 `[` 也不会冒出任何 `role=dialog`。

## 2. 底部唤起器：滚动感应

### 规则
常量在 `web/src/motion/useLauncherReveal.ts`：
- 向下滚过 `HIDE_AFTER = 180` 且单次位移 ≥ `SHOW_ON_UP = 24` → 收起；
- 反向滚 ≥ 24 → 立刻回来；
- 指针进入屏幕底部 `EDGE = 120` 这条带 → 立刻回来（触屏没有 hover，这一条只认鼠标/触控笔）；
- 悬停 / 焦点在按钮上时用 `hold(true)` 钉住，不会被滚动判据收走。

### 实现要点
- 收起是「位移 + 透明」，节点还在：`translate-y-[130%] opacity-0`，同时 `tabIndex=-1`、
  `pointer-events-none` —— 只是看不见但 Tab 还能落上去，等于埋了个坑。
- 位移挂在整条外层容器上，底部渐隐层跟着一起走；收起时底部不会留下一条没有内容的白雾。
- 滚动监听走 rAF 合并，指针监听 passive，不产生逐帧重排。

### 实测
- 滚下去 902px 后：容器类名含 `translate-y-[130%] opacity-0`，按钮 `tabindex=-1`、`pointer-events: none`。
- 向上滚 420px：`tabindex` 回到 0，容器回到 `translate-y-0 opacity-100`。
- 收起状态把指针挪到 y=820（底边 100px 内）：同样立刻回来。

## 3. 回顶按钮

- 新组件 `web/src/components/ScrollTop.tsx`：固定层与唤起器同一套内容边距（`max-w-[1180px] px-6`），
  右对齐、`bottom-24`，落在底部唤起器上方；详情页右下圆钮在 `bottom-5`，实测不重叠
  （回顶 y 736–772，圆钮 y 800–840）。
- 滚过 `1.2` 屏才出现；平滑回到顶部；隐藏时同样 `tabIndex=-1` + `pointer-events-none`。

## 4. 无限预取 + 滚动限速

### 预取
- `web/src/pages/FeedPage.tsx` 底部那条状态就是传感器：`IntersectionObserver` 的
  `rootMargin: "0px 0px 1200px 0px"` —— 离底部还有一屏半就开始取下一页。
- 传感器只在「还有下一页 / 正在取」时存在；回调读 ref（`feed.more` 每次渲染都是新函数），
  否则 observer 会被反复重建。
- 一屏都没铺满（筛选后只剩几条）时补一次：文档高度 < 视口 + 240 就自己再取一页。
- 状态条固定 `min-h-[56px]`：文案在「正在获取新内容…」和「继续往下滑，自动接着取」之间切换时，
  页面高度不变，不会抖；取完显示「已经到底了」，同样 56px。

### 加载状态拆分（`web/src/api.ts` `useFeed`）
- 新增 `moreLoading`：下一页不再复用首屏 `loading`，否则自动预取时列表上方会闪回「正在取内容…」。
- 单飞：`if (flight.current) return;` —— 滚动传感器可能在一个请求飞在路上时再触发一次。
- 追加不再 `abort` 正在飞的请求（那是把这一页丢掉再要一次，尾巴会被截断）；
  首屏/换筛选仍然 abort。
- 追加按 id 去重：`seen.has(entry.id)` —— 刷新一轮后条目可能移位，重复 key 会让 React 直接报错。

### 滚动限速（`web/src/motion/useScrollSpeedCap.ts`）
- 接管滚轮（`passive: false`）：把 delta 攒进 `pending`，每帧只放行 `MAX_SPEED = 2400 px/s × dt`。
- 不接管：事件目标在自己的滚动容器里（`ownsScroll`）、`Ctrl`+滚轮（缩放）、横向为主、
  `prefers-reduced-motion`。
- 实测：一次 4000px 的滚轮，60ms 时只走了 224px、660ms 时 1570px、约 2s 后停在 4001px。
  侧栏会话列表上滚轮：页面停在 400 不动，列表自己从 0 滚到 300。

### 实测（1280×860，924 条）
| 场景 | 结果 |
| --- | --- |
| 滚到底 | 卡片 60 → 90，抓到一个 `/api/feed?...cursor=...&limit=30` |
| 首屏 | 30 张，不自动多取（页面高过视口） |
| 控制台 | 0 条 error / pageerror |

## 5. 门禁
- `uv run --with pytest python -m pytest tests -q` → **87 passed**（新增 `tests/test_infinite_and_rail.py` 五条）。
- `cd web; node scripts/check-ui.mjs` → OK，没有违规。
- `cd web; npm run build` → dist/assets/index-Cc2FOlQ.js 467.76 kB / gzip 152.53 kB。

## 6. 未做
- 触屏没有「指针贴边」这条，只能靠滚动方向；也没有做「反向甩一下」的回弹手感。
- 滚动限速是全局的（所有页面都接管滚轮），设置页这类长表单也在内；目前只按 owned scroller 排除侧栏/抽屉。
- 预取没有做「取回来先不入列」的缓冲策略：仍然是取到就追加，靠传感器提前 1200px 兜住。
- 窄屏只看了 900 一档；没有真机 iOS/Android。
