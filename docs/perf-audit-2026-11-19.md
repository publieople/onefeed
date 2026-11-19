# OneFeed 界面性能审计（2026-11-19）

范围：`web/` 前端 + 与前端直接相关的后端接口（媒体代理、feed、detail）。方法：源码定位 + Chrome 真机测量（Playwright，1280×860，852 条真实数据、7 插件、后端 8799 serving `web/dist`），每项结论都有对照实验，不靠体感。

---

## 一、先说结论

整体不算慢：首屏 LCP 640ms、CLS 0.0001、DOM 803 节点，底子不差。真正的问题集中在**三处持续掉帧**和**三处白花流量/等待**：

| # | 问题 | 实测代价 | 严重度 |
|---|---|---|---|
| PF-1 | 顶栏 `backdrop-blur` | 滚动最长帧间隔 40ms → 13.6ms；换筛选布局耗时 54ms → 14ms | P0 |
| PF-2 | `.page-shell` 常驻 `will-change` | 整页被提升成 **4324px 高**的单张合成层；最长帧 27ms → 13.7ms | P0 |
| PF-3 | 1.6s 轮询 + 无 memo 的 30 张卡 | 空闲 10s 烧 0.4s 主线程（约 4%）；每次换筛选 30 卡全量重建 | P0 |
| PF-4 | `/api/media` 发 `max-age=0` | 再次打开详情，153 KB 整图重下（`If-None-Match` 也回 200） | P1 |
| PF-5 | 返回信息流必重取 feed | 每次返回：1 次 `/api/feed` + 20 张图 | P1 |
| PF-6 | 459 KB 单包 | 首屏可延后约 74 KB raw / 25 KB gzip | P1 |

修 PF-1、PF-2、PF-3 的收益是**肉眼可见的顺滑**，改动都很小（CSS 两处 + memo/轮询两处），建议与 Agent 交互改造同批做。

---

## 二、怎么测的（口径）

- 首屏：`load` + 4s 静置，CDP `Performance.getMetrics` 前后取差；`PerformanceObserver` 收 longtask / layout-shift / LCP。
- 掉帧：`requestAnimationFrame` 逐帧采样，统计 `>33ms`（两帧预算）的帧数与最大间隔。
- 滚动：以 55px/帧 平滑滚动 2.2s（约 3 屏），比鼠标滚轮可重复；另做轮询/筛选/切主题三次真实交互对照。
- 归因：同一页面注入 `!important` 覆盖 CSS 后重测，只有单一变量变化才下结论。图片多的平台（抖音/小红书）与纯文字平台（V2EX）分开测，避免图片加载污染 CSS 归因。
- 探针脚本留在 `.onefeed/tmp/probe_perf*.py`（可复跑）。

---

## 三、P0：三处持续掉帧

### PF-1 粘性顶栏的 `backdrop-blur` 是滚动卡顿主因

现象：快速滚动信息流，肉眼可见顿一下。

证据：
- `web/src/components/TopBar.tsx:43`：`className="sticky top-0 z-30 border-b border-line bg-paper/92 backdrop-blur"`。
- 滚动 3 屏基线：rAF avg 17.11ms、**max 173.4ms、6 帧 >33ms**。
- 注入 `header{backdrop-filter:none}` + 不透明底色：**max 13.6ms、0 帧 >33ms**。
- 同一口径换筛选（纯文字 V2EX 30 张卡）：布局耗时 **54ms → 14ms**，最长帧 67ms → 27ms，`>33ms` 从 1 帧变 0 帧。

为什么：粘性元素每帧都要对下层的滚动内容重新采样模糊，滚动时等于每帧多做一次全宽栅格化；`bg-paper/92` 的半透明还让整条顶栏不能走不透明快路径。

修法（二选一，改动都在 TopBar）：
1. 直接去掉 blur，用不透明 `bg-paper` + 底部 1px 边框。视觉几乎无差（`/92` 本来就是 8% 透光），收益最大。
2. 想保留玻璃感：滚动期间切不透明（`scroll` 监听 + 150ms 后回落），滚动中 `backdrop-filter:none`。

验收：滚动 3 屏 `>33ms` 帧数为 0，最长帧 <20ms。

### PF-2 `.page-shell` 常驻 `will-change` 把整页做成一张巨型合成层

证据：
- `web/src/theme.css:117-118`：`.page-shell { will-change: opacity, transform; }`；`web/src/App.tsx` 用它包 `Routes`。
- 实测该元素高 **4324px**（文档总高 4381px），computed `will-change: opacity, transform` → 页面几乎整体被提升到一张层里。
- 隔离测量：`will-change: auto` 后最长帧 **27ms → 13.7ms**，`>33ms` 0 帧。

为什么：常驻 `will-change` 等于告诉浏览器「这个元素随时要动」，于是永远保留合成层与纹理。整页一张 1280×4324 的层，滚动时 blur/raster 的粒度从「卡片级」变成「整页级」，同时显存占用成倍。

修法：只在需要的时候加。`runNav` 已经在往 `html` 上挂 `vt-running` 类（`web/src/motion/nav.ts`），把 `will-change` 挪到该类下：

```css
.page-shell { will-change: auto; }
html.vt-running .page-shell { will-change: opacity; }
```

验收：空闲时 computed `will-change` 为 `auto`；滚动最长帧 <20ms；转场观感不变。

### PF-3 轮询 + 无 memo：每 1.6 秒让 30 张卡重渲染一次

证据：
- `web/src/App.tsx:88-110`：`setInterval(tick, 1600)` 拉 `/api/progress`，然后 `setProgress(data.state)` —— **即使值完全没变，也是新对象引用**，App 必然重渲染。
- `web/src/pages/FeedPage.tsx:295-314`：每张卡外包一个 `motion.div`；`web/src/components/Card.tsx` 是普通函数组件，全仓 `React.memo` 数量为 **0**（`grep -r "React.memo|memo(" web/src` 无命中）。
- 空闲 10 秒（轮询在跑、无交互）：`TaskDuration 0.4008s`、`ScriptDuration 0.0779s`、无长任务、rAF max 26.2ms。→ 不是卡顿来源，但**白烧约 4% 主线程**，且是笔记本风扇与电量的一部分。
- 换筛选（图片多的平台）：`TaskDuration 323–540ms`、一次 **129ms 长任务**、`max gap 120–146.7ms`。其中图片解码是大头，但 30 个 framer-motion 实例的挂载/卸载同样在账上。

修法（按性价比排序）：
1. **轮询只在真的变化时 setState**：比较 `running/done/total/updated_at` 与各插件状态，相同就 return；或把 progress 挪进一个只让 TopBar 订阅的 store（`useSyncExternalStore`），App 不再因它重渲染。
2. **Card 加 `React.memo`**，且 `onOpen`/`vtNames` 保持引用稳定（现在 `openItem` 已是 useCallback，`vtNames` 每渲染都新建对象 → 用模块常量 `VT_BACK`/`VT_NONE`）。
3. 卡片位移动画（`layout`）当前只在 ≤12 张时开，这个闸门保留；但外层 `motion.div` 在 `layout=false` 时可退回普通 `div`，省 30 个 motion 实例。

验收：空闲 10s `TaskDuration < 0.1s`；改一次设置/开关不引起卡片重渲染（React DevTools Profiler 或加 render 计数探针）。

---

## 四、P1：白花的流量与等待

### PF-4 媒体代理明说不缓存，详情页每次重下整张图

证据：
- `onefeed/api.py:739-741`：透传 `etag`，但 `out["cache-control"] = "private, max-age=0"`。
- 实测：带 `If-None-Match` 再请求同一张图，返回 **200 + 完整 153222 字节**（74–89ms），**不是 304**。
- 入口：`web/src/pages/ItemPage.tsx:100`（图集）与 `:883` 附近（正文图）都拼 `/api/media/<id>/<slot>`。
- 附带：`onefeed/media.py:29` `SEMAPHORE = threading.BoundedSemaphore(4)`，视频与图片共用一个 4 并发闸门。

修法：图片 slot 的内容对同一 item 是稳定的（多数平台图片 URL 带签名但短时间内不变），可以放宽为 `private, max-age=3600`（或 `immutable`）+ 保持 ETag；视频保持 `max-age=0` 以支持拖动。若担心签名过期，前端在 `onError` 时带 `?refresh=1` 重取即可。

验收：同一详情页二次打开，DevTools 显示 `(from disk cache)`，网络 0 字节；图片闸门可与视频分开（视频 2 + 图片 4）。

### PF-5 从详情页返回信息流，必然重新拉 feed + 20 张图

证据：
- `web/src/api.ts:787-789`：`useEffect(() => { void load(null, false); }, [load, reloadKey])` —— 每次 mount 都请求，**即使 `feedCache` 有 seed**。
- 实测：进详情 `/api/feed` 0 次；返回时 **1 次 `/api/feed` + 20 张图**。
- 好消息：`web/src/pages/FeedPage.tsx:317` 的骨架只在 `items.length === 0` 时出现，所以有缓存时不闪骨架、不塌高度（这点设计是对的，别改）。

修法：有 seed 时走「stale-while-revalidate」——先呈现缓存，请求完成**只在数据真的不同**时替换数组（比较首条 id + count + next）；或 30s 内直接跳过请求。配合返回锚定（`restoreAnchor`）不会因为替换而错位。

验收：返回信息流 0 网络请求（或后台请求但无图片重下、无位移），返回后 1 帧内可见原卡片。

### PF-6 首屏 459 KB 单包，设置/详情/市场的代码都在里面

证据：`web/vite.config.ts` 无 `manualChunks`、无路由级 `import()`；`web/src/App.tsx` 顶部静态 import 四个页面。
分包实验（临时配置，已删）：vendor 331.83 KB（gzip 108.77）、index 60.12（20.17）、page-item 35.13（11.77）、page-settings 28.50（9.24）、page-market 10.73（4.26）。注意：**只加 manualChunks 不会延后加载**，要真省首屏必须对三个非首屏页面用 `React.lazy` + `Suspense`，可延后约 **74 KB raw / 25 KB gzip**，并顺带把 DOMPurify（仅详情页用）挪出首包。
首屏还有 2 个长任务共 309ms（235ms + 74ms），主要来自 459 KB 的解析与执行，拆包能削掉一部分。

验收：首屏 JS（gzip）< 95 KB；`/settings` 首次进入多一次 chunk 请求但 <30ms。

### PF-7 头像与封面：16×16 的坑位拉 2048px 原图

证据（首屏 14 张图 / 567 KB）：
- 封面自然尺寸 1890×1063、1745×981、1920×1080、1600×900，实际显示 **338×190**（`web/src/components/Card.tsx:66-77`，无 `width/height`、无 `decoding`、无 `fetchPriority`）；单张最大 312 KB、耗时 1951ms。
- 作者头像：自然尺寸 512×488、**2048×2048**、384×384，实际显示 **16×16**（`Card.tsx:282-291`）。

修法：
1. 头像最省事：直接用已有的字母色块兜底（`Card.tsx:292-295` 已实现），不再加载远镜头像；或后端 `/api/thumb?u=<url>&w=32` 走一次代理缓存。
2. 封面：在插件层把缩略图地址拼好（B 站 `@672w_378h_1c.webp`、抖音 `?x-oss-process=...`），前端优先 `cover_thumb` 回退 `cover`；同时补 `decoding="async"`，首屏前 3 张 `fetchPriority="high"`，其余 `low`。
3. 卡片可加 `content-visibility: auto`（配 `contain-intrinsic-size`），离屏卡片跳过渲染。

验收：首屏图片总字节 <200 KB；滚动时不再出现 300 KB 级单图。

---

## 五、P2：清理与顺手项

- **PF-8 预取缓存无上限**：`web/src/api.ts:495` 的 `prefetched` 只在读取时判 TTL，**从不删除**；每悬停一张卡还并发拉 item + detail 两个请求（detail 冷路径实测 7.9s）。→ 改 LRU（上限 40），悬停离开即 `abort`，detail 预取等 item 命中后再发。
- **PF-9 `feedCache` 无上限**：`api.ts:728`，筛选组合多了会一直涨。→ 上限 8 + LRU。
- **PF-10 TopBar 事件重复绑定**：`web/src/components/TopBar.tsx:32-36` 的 `useEffect` **没有依赖数组**，每次渲染都解绑再绑 `onefeed:theme`；配合 1.6s 轮询，等于每 1.6 秒做两次 DOM 事件操作。→ 加 `[]`，内部用 ref 取最新 `flipTheme`。
- **PF-11 切主题 0.7s `clip-path`**：实测 `TaskDuration 259.9ms`、`RecalcStyleCount 70`、2 帧 >33ms。观感是加分项，可保留；建议把 `html.nav-vt * { transition: none !important }`（`theme.css:267-270`）收窄到实际参与的元素，避免全文档样式重算。
- **PF-12 换筛选的图片洪峰**：一次换筛选 12 张新图 2062 KB 同时起。→ 配合 PF-7 的缩略图 + `fetchPriority` 分级。
- **PF-13 详情冷启 7.9s**：`GET /api/item/{id}/detail` 走插件抓取，未缓存时 7870ms。前端已有「Agent 正在看这条内容」骨架，但可在后端加 detail 短期缓存（60s）与并发去重，避免来回点两次各抓一遍。

---

## 六、与本轮 Agent 改造怎么合

| 批次 | 内容 | 关系 |
|---|---|---|
| 批次 A（先做，半天） | PF-1 去掉顶栏模糊、PF-2 will-change 改按需、PF-10 TopBar 依赖数组 | 纯 CSS/一行 JS，先让页面变顺，后续改造都在顺的地基上 |
| 批次 B（与 Agent 改造同批） | PF-3 轮询只变才 set、Card `React.memo`、motion 外层降级 | 与 AgentProvider 拆分重渲染同批，避免二次改 App.tsx |
| 批次 C（与详情页改造同批） | PF-4 媒体缓存头、PF-13 detail 缓存、PF-7 缩略图/头像 | 详情页要改成 hero + 右栏，顺手把图换小 |
| 批次 D（收尾） | PF-5 返回不重取、PF-6 路由懒加载、PF-8/9 LRU | 独立性最强，放最后不影响主流程 |

不属于本轮但值得记：`onefeed/media.py` 的 4 并发闸门建议视频/图片分开，避免看视频时图集卡住。

---

## 七、没测到的

- Firefox / Safari 的 `backdrop-filter` 与 View Transition 表现（本机只有 Chrome）。
- 真实窄屏（<768px）下的 LayoutDuration；本次全部 1280×860。
- 首屏在冷启动后端（插件抓取中）时的表现，本次后端是 852 条已采数据。
- 长时间（>10 分钟）停留的内存曲线：`prefetched`/`feedCache` 无上限的影响只会随时间显现，未量化。
