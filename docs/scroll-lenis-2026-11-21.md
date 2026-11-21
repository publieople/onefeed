# 滚轮换回 Lenis 调校档（2026-11-21 下午）

用户第三次说滚动不满意（2026-11-20「和我想象的滑动效果不一样」、11-21 上午「还是跳变式的」、11-21 下午「找找别人实现得比较好的」）。这次没有直接改，先做了一个九宫格对照页让用户自己滚，用户选定 **3 号：Lenis 调校档**。

## 一、为什么上一版（自研两段式）被判「跳变」

上一版为了让滚轮「当帧跟手」，事件落在同一帧就写掉 `delta × 1.15 × 0.62`。Windows 一格滚轮约 100px，于是 **71px 在落下那一帧就走完了**，剩下 44px 才慢慢追。眼睛看到的是「先跳一下、再滑一段」——不是 bug，是那个参数取舍的直接后果。预览页把九种方案并排放在一起，用户比完选了最连贯的那一档。

## 二、预览页与九个候选（.onefeed/tmp/scroll-preview/index.html，端口 8823）

同一份 12 张卡，每块右上角实时显示「变化帧数 / 最大单步 / 用时 / 位移」。各自单独开页、用合成 `WheelEvent` 滚 100px 的读数：

| # | 方案 | 最大单步 | 用时 | 手感 |
| --- | --- | --- | --- | --- |
| 1 | 原生（浏览器默认） | — | — | 基线 |
| 2 | Lenis 默认 lerp 0.1 | 12px | 890ms | 很滑，尾巴长 |
| **3** | **Lenis 调校 duration 0.85 + easeOutQuart** | **6px** | **613ms** | **最连贯、收尾干净** |
| 4 | Locomotive Scroll v5 | 7px | 889ms | 接近 Lenis 默认，另带视差 |
| 5 | 弹簧 stiffness 320 / damping 34 | 11px | 451ms | 无过冲，比 Lenis 利落 |
| 6 | Smooth Scrollbar damping 0.1 | 10px | 362ms | 偏重，会自带滚动条 |
| 7 | 线上旧版（两段式 0.62/τ55） | 71px | 269ms | 起手猛、一帧可见的跳 |
| 8 | 同引擎轻惯性 0.15/τ160 | 17px | 866ms | 飘、起手轻 |
| 9 | 摩擦惯性（速度积分） | 8px | 660ms | 触控板「推一下滑一段」 |

没收录：ASScroll（会把容器设 `position: fixed` 接管整页，塞进小框失真）、GSAP ScrollSmoother（要买授权）、OverlayScrollbars（只管滚动条外观）。

## 三、落地实现（web/src/motion/useSmoothWheelScroll.ts 整份重写）

一个容器一个 `Lenis` 实例，加一个页面实例，**共用一个 rAF 循环**：

```ts
const DURATION = 0.85;
const WHEEL_MULTIPLIER = 1;
const EASING = (t: number) => 1 - Math.pow(1 - t, 4); // easeOutQuart
const IDLE_FRAMES = 6;
// options: { duration, easing, wheelMultiplier, smoothWheel: true, overscroll: false, autoRaf: false }
```

要点：

- **autoRaf: false**，自己喂帧：`pageLenis.raf(time)` + 每个容器 `lenis.raf(time)`，任一个 `isScrolling` 就继续；连续 6 帧没人滚就 `cancelAnimationFrame`，空闲时 0 回调（实测 CPU 从 6–7% 回到 0.4% 那段是旧版，新版同样靠这招停）。
- **边界接力**：侧栏滚到顶还往上、到底还往下，在容器的捕获阶段把这一格拦下来（`preventDefault` + `stopImmediatePropagation`），换算成像素后交给页面实例继续缓动 —— 两段手感连成一段，不会「侧栏停了页面才开始一格一格跳」。
- **页面实例不接管侧栏**：`prevent: (node) => node instanceof Element && !!node.closest('[data-smooth-scroll]')`，否则两套实例在同一格滚轮上打架。
- **模态锁**：`pauseDepth > 0` 或 `isPageScrollLocked()` 时在 document 捕获阶段吞掉滚轮（确认框、快捷键表、灯箱、收藏备注框）。暂停用计数，两层模态嵌套时先关的不能把后关的解掉。
- **豁免**：`prefers-reduced-motion` 与 Mac（触控板自带惯性，再加一层会过冲）直接跳过接管。
- **程序化滚动走引擎坐标系**：`scrollInstant(el, top)` —— 有实例就 `lenis.scrollTo(top, { immediate: true })`，否则 `scrollTo({ top, behavior: 'instant' })`。Agent 对话流吸底用的就是它。
- 六处列表仍挂 `data-smooth-scroll`（Agent 会话列表、图标轨、右栏收藏/稍后再看/AI 总结/同题、对话流）；容器上的 `overscroll-contain` 全部去掉，否则滚动链在边界就断了，接力也滚不动。

## 四、实测（Chrome headless 1440×900，http://127.0.0.1:8799，961 条数据）

采样方式：`document` 捕获阶段监听 `scroll` + `performance.now()`，**不用 rAF**。

| 场景 | 首动 | 变化帧 | 用时 | 位移 | 最大单步 |
| --- | --- | --- | --- | --- | --- |
| 侧栏 1 格 | 41–54ms | 37–38 | 599–667ms | 94–100px | 6px |
| 页面 1 格（fresh） | 15–42ms | 36–38 | 599–613ms | 100px | 6–10px |
| 侧栏到底再滚一格 | — | 47 | 680ms | 页面 400px | 24px |

与预览页 3 号面板（38 帧 / 6px / 613ms）逐项对齐，说明接的是同一档参数。模态：`?` 打开帮助层后滚轮 `scrollY` 仍 0，Esc 关闭后滚 200 → 200。

**采样的坑**：先用的 rAF 采样器在这个 headless 环境里会被节流（两次报出 116–122px 的「大单步」，同一时刻 rAF 间隔 293–440ms），看起来像引擎跳变，其实是采样漏帧。换成 scroll 事件采样后读数才稳定。这一条以后测滚动都适用。

## 五、代价与旋钮

- 体积：主包 430.52 kB → **450.40 kB**（gzip 137.60 → **143.39 kB**），即 Lenis 约 5.5 kB gzip。
- 尾巴：duration 0.85 意味着一格约 600ms 走完，比上一版的 267ms 长；换来的是没有任何一帧可见的跳。嫌慢就改 `DURATION`（0.7 更紧、1.0 更飘）。
- `WHEEL_MULTIPLIER`（默认 1）控制「一格滚多远」，Windows 100px 一格正好，想快改 1.15。
- `EASING` 换成 `1 - Math.pow(1 - t, 3)` 会更冲一点，`(t) => t` 就退化成线性。
- Mac 与 `prefers-reduced-motion` 不接管，走浏览器原生。

## 六、验证

```
uv run --offline --with pytest python -m pytest tests -q   # 116 passed
node web/scripts/check-ui.mjs                              # OK
pwsh scripts/preflight.ps1                                  # 全绿
```

探针：`probes/probe_lenis_page.py`（scroll 事件版，最终采用）、`probes/probe_lenis_scroll.py`（rAF 版，留作对照）。

## 七、不做

- 不接管触控板/Mac 惯性（过度叠加会过冲）。
- 不做「滚动条外观替换」（OverlayScrollbars 那类），与手感无关。
- 不引 GSAP/ScrollSmoother：授权 + 双运行时，收益不抵。