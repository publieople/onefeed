# 滚到一半滑不动 + AI 条收起动画消失（2026-11-21）

两个都不是「调参数」，是我上一轮换滚动引擎与浮层 CSS 时带出来的真回归。都已修，并各留了一条静态守门。

## 一、滚到 1916 就再也下不去

### 现象
信息流往下滚，滚到某处（首屏高度那个位置）滚轮完全没反应，缩略图里能看见下面明明还有卡片。
探针 `.onefeed/tmp/probe_stuck.py`（1440×900，用 `pg.mouse.wheel(0, 400)`）：

| 滚轮次数 | scrollY | 页面可滚上限 |
| --- | --- | --- |
| 起始 | 0 | 1916 |
| 4 | 1546 | 4314（自动加载了下一批） |
| 8 | **1916** | 4314 |
| 14 | **1916** | 4314 |

### 根因
Lenis 自己挂在 `document.documentElement` 上的 `ResizeObserver` 管 limit：
`web/node_modules/lenis/dist/lenis.mjs` 里 `content` 默认就是 `document.documentElement`，
`onContentResize` 读的是 `this.content.scrollHeight`。

而我们去信息流是往 `body` 里追加卡片：`body` 长高了，`html` 的盒子尺寸没变 —— 观察不触发，
`dimensions.limit` 停在首次加载的 1916。滚轮目标被 clamp 在旧上限，于是越滚越早「到底」。

这也解释了为什么以前手写引擎没这毛病：那版每帧现算 `maxPos()`，根本没有缓存。

### 修法（`web/src/motion/useSmoothWheelScroll.ts`）
```ts
function syncPageLimit(): void {
  if (!pageLenis) return;
  if (pageLenis.limit === pageLimit()) return;   // 现算 scrollHeight - innerHeight
  pageLenis.resize();
}
```
三处触发：
1. `bodyObserver`（`ResizeObserver` 盯 `document.body`）—— 内容长高就重算，80ms 去抖；
2. `onWheelCapture` 里 120ms 节流对一次实时值 —— 兜住观察回调还没跑的那一瞬；
3. `forwardToPage` 开头 —— 侧栏滚到底接力给页面时，别把目标 clamp 在旧上限。

### 验证
同一探针复跑：`0 → 1546 → 3133 → 4707 → 6278 → 7837 → 9461 → … → 11864`，
上限随之 `4314 → 6713 → 9115 → 11522 → 13923` 一路增长，不再卡死。

### 探针陷阱（记下来别再踩）
`window.dispatchEvent(new WheelEvent(...))` 打不动页面（scrollY 恒 0、scroll 事件 0 次）：
Lenis 的 VirtualScroll 监听的是 window 上的真实事件路径，合成事件进不去。必须用 `pg.mouse.wheel`。

## 二、底部 AI 条的收起动画没了

### 现象
滚动往下时唤起器「啪」地消失，没有下滑淡出。探针 `.onefeed/tmp/probe_ai_pill2.py` 采样
`[data-agent-launcher-wrap="pill"]`：class 切到 hidden 的那一帧 opacity 直接从 `1.00` 变成 `0.00`，
transform 从 `translateY(0)` 直接变成 `translateY(78px)`，中间零帧。

### 根因
`web/src/theme.css` 的 `.shell-inset-x` 为了跟随侧栏宽度补间，整条写了 transition：

```css
.shell-inset-x {
  transition: left 260ms ..., right 260ms ...;
}
```

然后是元素上同时挂着 Tailwind 的 `transition duration-300 ease-out`（要动 transform/opacity）。
`transition` 是简写，**`transition-property` 是整条覆盖的**：computed 实测
`transition-property: left, right / duration 0.26s, 0.26s` —— transform 与 opacity 根本没进列表。
`ScrollTop` 也挂了这个类，但它要动的属性在内层 button 上，所以只有唤起器和抽屉中招。

### 修法
同一个类里把四条属性写全，拆成两条是无效的（同样会互相顶掉）：

```css
.shell-inset-x.shell-lift {          /* 唤起器 corner / pill */
  transition: left 260ms …, right 260ms …, transform 300ms ease-out, opacity 300ms ease-out;
}
.shell-inset-x.shell-lift-sheet {    /* 底部抽屉，原时长 220ms */
  transition: left 260ms …, right 260ms …, transform 220ms ease-out, opacity 220ms ease-out;
}
```

- `web/src/agent/AgentSurface.tsx` 三处容器换成 `shell-inset-x shell-lift` / `shell-lift-sheet`，
  删掉 Tailwind 的 `transition duration-300 ease-out`（留着只会被顶掉，读代码的人会以为它在生效）。
- `prefers-reduced-motion: reduce` 下两条也进 `transition: none`，节点照旧在。

### 验证
同一探针：opacity `1.00 → 0.93 → 0.86 → 0.43 → 0.33 → 0.24 → 0.12 → 0.04 → 0.00`，
transform `0 → 5.7 → 11.2 → … → 78`，约 300ms 收完 —— 是滑动，不是跳变。

## 三、守门与门禁

- 新增 `tests/test_motion_coverage.py::test_page_limit_follows_content_and_lift_keeps_its_transition`：
  钉住 `syncPageLimit`、`pageLenis.limit === pageLimit()`、`bodyObserver.observe(document.body)`、
  `forwardToPage` 里先同步上限、两条 lift 过渡的时长、reduce 覆盖，以及旧的 `transition duration-300`
  不许再出现。
- `pwsh scripts/preflight.ps1` 全绿：pytest **117 passed**、离线 26 项、check-ui 无违规、
  build `dist/assets/index-BkF7Ewa7.js` 450.62 kB / gzip 143.49 kB。

## 四、边界
- 只修了「上限不更新」与「过渡被覆盖」，滚动的手感参数（`DURATION 0.85` / `EASING` / `WHEEL_MULTIPLIER`）没动。
- 抽屉 220ms 与唤起器 300ms 沿用原来的数，没顺手统一 —— 两者视觉上不是同一层。
- 真机 GPU、Safari 仍未验证（headless 走软件光栅，长任务偏悲观）。
