# OneFeed 刷新体验改进方案（v2：含主视图清场—登场）

> 2026-11-22。针对「点了刷新，除图标转、底部弹条提示外主界面毫无反应」。
> v2 增加用户指定需求：**主视图旧内容全部收起 → 新卡片逐个弹出**。
> 总目标：刷新全程可见、可读、可处置；动效只发生在列表区域，不推正文。

## 0. 一句话结论

不是刷新慢，是**刷新不可见**。后端每完成一个平台就把 `status / count / error / next_at` 写进了 `/api/progress`，前端只读了 `running / done / total` 三个数，画成一条 2px 线和右上角 16px 的「3/7」。数据齐了 99%，界面用了 1%。

## 1. 现状（源码 + 实测）

### 1.1 一次刷新现在发生什么

| 阶段 | 代码 | 用户看到 |
| --- | --- | --- |
| 点按钮 | `web/src/components/TopBar.tsx:73-81` → `web/src/App.tsx:203-231` → `POST /api/refresh` | 底部 toast「开始刷新」，3.2s 消失 |
| 采集 30–90s | `web/src/App.tsx:151-201` 每 1600ms 轮询 `/api/progress`；`TopBar.tsx:15-18` 只算 running/done/total/pct | 图标转圈（:80）、右上角「3/7」（:64-72，**md 以上才显示**）、页头下缘 2px 进度条（:113-116） |
| 列表 | `FeedPage.tsx:445-452` | 刷新期间列表整体 `opacity-55`，没有任何「正在刷新」文案；`:419-423` 的「正在按新条件筛…」只对应筛选变化 |
| 结束 | `App.tsx:160-189` | toast「刷新完成：新增 N 条 · X 个平台失败 · Y 个平台冷却中」，3.2s 消失、不可展开、不能重试 |
| 结束后的列表 | `App.tsx:161` `setReloadKey` → `useFeed` 重取 | 卡片整批换掉，只有 `.rise` 的 22ms 阶梯淡入，看不出「哪些是新的」 |

### 1.2 已有的信号 vs 用到的信号

| 信号 | 后端有 | 前端 |
| --- | --- | --- |
| `running` | ✓ | ✓ |
| `done / total` | ✓ | ✓ |
| `plugins[].status`（queued/running/ok/failed/skipped） | ✓ | ✗ |
| `plugins[].count`（该平台抓到几条） | ✓ | 只在结束时求和进 toast |
| `plugins[].error`（失败原因，截 600 字） | ✓ | ✗ |
| `plugins[].next_at`（冷却到点） | ✓ | 只在「全部冷却」时取过一次最小值 |
| market `{checked,updated,failed}` | ✓ | ✗ |

证据：`onefeed/service.py:59-73`（state 形状）、`:96-140`（逐平台排队/冷却，写 `next_at` 与 note）、`:143-150`（完成即重算 done）、`:152-203`（串行跑，逐平台写 status/count/ms/error）、`onefeed/api.py:899-915`（202 + state / 409 refresh_running、GET progress）；前端类型 `web/src/api.ts:64-75` 连 market 都没声明。

### 1.3 四个具体毛病

1. **采集中主界面零变化**：30–90 秒里唯一变化是 2px 条，移动端连「3/7」都没有（`md:inline-block`）。无法判断「在跑 / 卡死 / 没抓到」。
2. **单项状态不可见**：哪个平台在抓、哪个失败、原因，全被压成结束后的一个总数；而抓取本身是逐平台串行（`service.py:152-203`），恰好能做「逐个亮起」。
3. **结果没有落点**：结束时整表替换，用户不知道多了什么；位置靠 `restoreAnchor` 维持，只在「从详情返回」时有锚点。
4. **结束后的重排是无声的**：`.rise` 对每一张卡都放一遍 22ms 阶梯，新老混在一起，视觉上等于「全都变了」——这正是本次要改掉的观感。

## 2. 参考主流做法，抽三条原则

| 产品 | 做法 | 可借的点 |
| --- | --- | --- |
| X / Twitter | 时间线顶部浮「Show 42 posts」，不自动插入 | 新内容给入口，不抢滚动位置 |
| Feedly / Inoreader | 逐源进度 + 失败源带重试 | 进度按「源」拆，失败可单点重试 |
| GitHub Actions / Vercel | 阶段条 + 每步状态 + 失败展开日志 | 阶段词 + 可展开错误 |
| Steam / Chrome 下载 | 队列逐项进度，失败项独立重试 | 每项独立状态，不共用一个 spinner |
| Linear 同步态 | 小徽标常驻，不打断 | 进度是常驻状态，不是一次性 toast |

三条原则：

1. **进度分级**：全局（还差几个）→ 单项（谁在跑、谁失败）→ 结果（多了什么）。
2. **结果可消费**：新内容不能静默替换列表。本次升级为「清场 + 逐个登场 + 新卡标记」，让结果自己走出来。
3. **失败可处置**：每个失败项旁边有重试，而不是一句「2 个平台失败」。

## 3. 目标状态机

后端只有布尔 `running`，无法表达「抓完了但还在整理」。补 `phase`：

```
idle → fetching → settling → done | partial | empty
```

| phase | 含义 | 界面 |
| --- | --- | --- |
| `idle` | 没有运行 | 状态条收起 |
| `fetching` | 至少一个平台在跑 | 进度条实心增长 + 平台 pill 逐个亮 |
| `settling` | 平台都结束，prune/cluster 未完成（<1s） | 进度条脉冲，文案「整理中」 |
| `done` | 全部成功 | 结果态 + 清场登场 |
| `partial` | 有 failed | 结果态 + 失败项可重试（同样清场登场） |
| `empty` | 全部 skipped（冷却） | 「都在冷却，最早 HH:MM 可抓」+ 强制抓取，**不播动效** |

`settling` 很短但必须有：`onefeed/service.py` 在 `_run` 之后才 prune/cluster，只认 running 会把这一秒误判成「已完成」并立刻重取列表。

在前端，动效有自己的相位（与后端 phase 解耦）：

```
idle → collapsing（收旧） → revealing（立新） → idle
```

## 4. 常驻反馈：L1 顶栏 + L2 内联状态条

### L1 顶栏

- 2px 进度条保留（`TopBar.tsx:113-116`），语义化：fetching 实心、settling 脉冲、done 后淡出。
- 「3/7」从 11px 提到 12px，**移动端也显示**（去掉 `hidden md:inline-block`，窄屏只显示 `3/7`）。
- 刷新按钮 running 时**不再 disabled**（`TopBar.tsx:75` 现在把唯一入口关掉了）：点击即展开 L2 状态条。
- title：「正在抓 V2EX，已完成 3/7」。

### L2 信息流内联状态条

位置：筛选胶囊之后、摘要行之前（`FeedPage.tsx:419` 之前），`min-h-[40px]` 固定占位，单行 flex + truncate。**高度恒定，正文不动**。

进行中：

```
[正在抓取 4/7]  ● B站  ● 小红书  ⟳ 抖音  ✓ 掘金 12  ! V2EX        已 23s
```

- pill 四态：灰点排队、脉冲点抓取中、✓+条数完成、! 失败。
- 轨道横向滚动 + 两端渐隐（复用 `TabRail.tsx` 的做法），窄屏只显示 3 个 + 「+4」。
- 「已 23s」用 `started_at` 算，不做假的剩余时间。

结束后切成结果态（同一条、同高）：

```
[这一轮 +42 条]  B站 18 · 小红书 12 · 抖音 8 · V2EX 4 · 知乎 0 ｜ 3 个冷却 ｜ 失败 2  [看新内容] [重试失败] [收起]
```

- 「收起」写 localStorage，只隐藏本轮。
- 点失败 pill 展开一行 error（截 120 字）+「只重试这个平台」→ `POST /api/refresh {platforms:[pid], force:true}`。
- 全冷却（phase=empty）：「都在冷却，最早 12:31 可抓」+「强制抓取」（复用 `confirmDialog`）。
- demo 模式文案「演示模式：重放本地样例」，避免「+0 条」被当成故障。
- 有清场登场动效时，结果态左端文案从「看新内容」改成「刚放进来的 42 条」——内容已经在眼前，不再给入口。

## 5. 主视图：清场 → 逐个登场（本次新增的核心）

### 5.1 要解决什么

现在的结束态是「整表无声替换 + 每张卡都淡入一遍」，用户既看不出差异，也没有「新东西到了」的仪式感。目标改成一次**有明确因果的演出**：我先请你让开（旧内容收起），再把新的逐个放上来。

它同时解决三件事：结果有落点（新卡自己走出来）、差异可读（新卡带标记，老卡不重播）、情绪到位（刷新从一个后台动作变成一次可感知的更新）。

### 5.2 触发闸门（六条，缺一不播）

| # | 条件 | 原因 | 不满足时 |
| --- | --- | --- | --- |
| 1 | 刷新真的结束（`running` 真→假），且本轮新增 > 0 | 换筛选、排序、搜索、返回、首屏加载都会改列表，不能播 | 不播 |
| 2 | 用户此刻在列表顶部附近：`grid.top > -0.6 × innerHeight` | 在看不见的地方拆房子，回来发现全变了，是最坏体验 | 降级为「有 N 条新内容」胶囊 |
| 3 | 没有筛选/搜索条件在变化（本轮 `query` 未变） | 筛选变化有 T5 的 layout 动画，两套动效会打架 | 不播 |
| 4 | 新条目 ≥ `FULL_PLAY_MIN`（默认 3） | 为了 +1 条把 30 张卡收掉是失衡的；常量可设 0 强制每次都播 | 轻量档：只让新卡 pop，不收场 |
| 5 | 非 `prefers-reduced-motion`、非窄屏（< 640） | 前庭敏感与性能；窄屏一屏只看得见 1.5 张卡，收场等于白屏 | 直接换数据，状态条照常播报 |
| 6 | 页面可见（`document.visibilityState === "visible"`） | 隐藏页 rAF 被节流，动画进度不可控 | 直接跳过结算 |

**如何拿到"刷新结束"这个信号**：现在 `ctx` 里只有一个 `reloadKey`，它也会被筛选、bump 改动。必须新增独立序号：

```ts
// web/src/App.tsx:160-189 内部，running 真→假时
if (wasRunning.current && !state.running) {
  setReloadKey(k => k + 1);                    // 列表重取（所有路径共用）
  if (newTotal > 0) setRefreshSeq(s => s + 1); // 只有这里 +1，只给动效用
}
```

`OutletCtx`（`App.tsx:33`）加 `refreshSeq: number`；`FeedPage` 用 `playedSeq` ref 记录已消费过的序号，避免重复播。

### 5.3 时间轴（总计 0.8–1.25s）

以「旧 30 张、新 12 张」为例：

| 拍 | 起点 | 时长 | 做什么 | 参数 |
| --- | --- | --- | --- | --- |
| 0 锁场 | 0ms | — | 列表容器量高并锁 `minHeight`；`.rise` 停用；`layout` 动画停用；`aria-busy=true` | 禁止 hover 抬升与点击 |
| 1 收 | 0 | 200ms/张，间隔 18ms，cap 12 | 旧卡逆序倒塌：`opacity→0`、`translateY(-8px)`、`scale .97` | `cubic-bezier(.4,0,1,1)`，即"被抽走"的加速感 |
| 2 空 | 约 400ms | 60ms | 留白一拍（容器高度仍是旧值） | 没有这 60ms，收→立会像闪屏 |
| 3 立 | 400ms | 160ms | 会保留的老卡整组淡入（不逐个、不计入阶梯） | `opacity 0→1`、`translateY(6px)→0` |
| 4 登场 | 440ms | 300ms/张，间隔 45ms，cap 12 | 新卡按列表顺序逐个弹出 | `opacity 0→1`、`translateY(18px)→0`、`scale .96→1`，spring 约 `{300, 30}` |
| 5 收尾 | 最晚约 1.25s | — | 解除 minHeight、清 `aria-busy`、新卡「新」标记 2.4s 后淡出、焦点/读屏播报 | — |

- 12 张以上：第 13 张起不再加延迟，跟随最后一拍一起出现（否则 30 张要飘 2.5s）。
- 新卡 < 3 张时整段自然变短（3 张：90 + 300 ≈ 0.83s）。
- 时间常数集中在一处（`web/src/motion/tokens.ts` 加 `REVEAL = { collapse: 200, gap: 18, hold: 60, base: 160, pop: 300, step: 45, cap: 12, min: 3 }`），不散落在组件里。

### 5.4 怎么实现（不依赖 exit 动画）

**硬约束（本项目踩过）**：不能用 `AnimatePresence` 的 exit 驱动收场。隐藏标签页里 rAF 被节流到 ~1fps，退出动画永远收不了尾，元素会卡在 DOM 里（之前 AI 面板就因此关不掉）。所以：

- 收场用 **CSS transition + 相位状态机**，不挂 exit 动画；
- 相位推进用 `setTimeout` 定时器，**不依赖 `onAnimationComplete`**；再加一个兜底定时器（`总时长 + 400ms`）强制回 `idle`；
- 卡片渲染的列表在两相位间切换：`phase === "collapsing" ? oldItems : feed.items`。用「保持旧数组」而不是「保持旧 DOM」，React 会重渲染但视觉由 CSS 接住。

```tsx
// FeedPage.tsx 骨架
const [phase, setPhase] = useState<"idle" | "collapsing" | "revealing">("idle");
const [oldItems, setOldItems] = useState<FeedItem[] | null>(null);
const playedSeq = useRef(0);
const prevIds = useRef<Set<string>>(new Set());
const boxRef = useRef<HTMLDivElement>(null);      // 包住网格，量高用
const gridEl = grid.ref;                           // 已有 section ref

// 1) 触发（effect 依赖 refreshSeq / loading / items）
useEffect(() => {
  if (ctx.refreshSeq === playedSeq.current) return;
  if (phase !== "idle" || feed.loading || !feed.items.length) return;
  const fresh = feed.items.filter(i => !prevIds.current.has(i.id));
  playedSeq.current = ctx.refreshSeq;            // 无论播不播都消费掉
  if (fresh.length < REVEAL.min) return;         // 条件 4，轻量档另行处理
  const top = gridEl.current?.getBoundingClientRect().top ?? 0;
  if (top < -window.innerHeight * 0.6) return;   // 条件 2 → 走胶囊
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  if (document.visibilityState !== "visible") return;
  startPlayout(feed.items);                      // 记 oldItems、锁高、phase="collapsing"
}, [ctx.refreshSeq, feed.loading, feed.items, phase]);

// 2) 相位推进（每相位一个定时器 + 兜底）
useEffect(() => {
  if (phase === "idle") return;
  const ms = phase === "collapsing"
    ? REVEAL.hold + REVEAL.collapse + Math.min(REVEAL.cap, oldItems!.length) * REVEAL.gap
    : REVEAL.pop + Math.min(REVEAL.cap, feed.items.length) * REVEAL.step;
  const t = setTimeout(() => {
    if (phase === "collapsing") setPhase("revealing");
    else settle();                                 // 清 minHeight / aria-busy
  }, ms);
  const guard = setTimeout(settle, ms + 400);      // 兜底：无论动画如何都收尾
  return () => { clearTimeout(t); clearTimeout(guard); };
}, [phase]);

// 3) 用户滚动 / 按键 → 立刻结算（不与用户抢滚动）
useEffect(() => {
  if (phase === "idle") return;
  const kill = () => settle();
  addEventListener("wheel", kill, { passive: true, once: true });
  addEventListener("touchmove", kill, { passive: true, once: true });
  addEventListener("keydown", kill, { once: true });
  return () => { removeEventListener("wheel", kill); removeEventListener("touchmove", kill); removeEventListener("keydown", kill); };
}, [phase]);
```

**高度锁（最关键的一处）**：收场时总高度会缩，页面下方（加载更多、页脚）会往上跳；若缩到比视口还短，浏览器会强制夹 `scrollY`，于是"整页位移"就发生了。做法：

1. 开场前 `const h = gridEl.current.offsetHeight`，写到外层容器 `style.minHeight = h + "px"`；
2. 收场期间容器高度保持不变（列表缩，容器不缩）；
3. 登场结束后清掉 `minHeight`；若新内容更高则自然撑开，只有"新内容更矮"时才有一次收尾位移，且发生在演出结束、用户已看到结果之后。

**焦点**：若 `document.activeElement` 落在将被收掉的卡片里，开场时把焦点交给网格容器（`tabIndex={-1}`），不要掉到 `body`；登场后不自动抢焦点。

**样式**（`web/src/theme.css`，与现有 `.rise` 并列）：

```css
.feed-card { transition: opacity .2s var(--ease-out), transform .2s var(--ease-out); }
.feed-card[data-out="1"] {
  opacity: 0; transform: translateY(-8px) scale(.97);
  transition-delay: calc(var(--i) * 18ms);       /* 逆序用 calc((12 - var(--i)) * 18ms) */
  pointer-events: none;
}
@keyframes card-pop {
  from { opacity: 0; transform: translateY(18px) scale(.96); }
  to   { opacity: 1; transform: none; }
}
.feed-card[data-in="new"] {
  animation: card-pop .3s cubic-bezier(.16,1,.3,1) both;
  animation-delay: calc(var(--j) * 45ms);
}
.feed-card[data-in="carry"] { animation: card-fade .16s ease-out both; }
```

- 只用 `opacity / transform`，不动高度、不 blur（blur 30 张会掉帧）。
- 演出期间给容器加 `will-change: transform` 类，结束移除，避免长期占用图层。
- reduce-motion 下 `.feed-card[data-in]` 一律 `animation: none`（GSAP/框架无关，纯 CSS 就能覆盖）。

### 5.5 新卡怎么认、怎么标

- **认**：`prevIds` 是上一轮渲染的 id 集合，刷新前快照；新列表里 `!prevIds.has(id)` 即新。不改后端契约也能做。
- **标**：新卡左上角 2px 强调色左缘 + 一个 `新` 小胶囊，2.4s 后淡出（`opacity 1→0`，不改变布局）。
- **排序**：只有 `sort=新鲜度` 时新卡才出现在首屏；`sort=热度` 下新内容可能一条都不在前 30 → `fresh.length === 0` → 不播，结果态给「切到最新看新内容」。
- 新卡如果落在第 2 屏（首屏 30 条里没有），就谈不上"逐个弹出"，走胶囊。

### 5.6 与现有动效的冲突（必须一起改，否则会双重动画）

| 现有 | 位置 | 冲突 | 处理 |
| --- | --- | --- | --- |
| `.rise` 每张卡 22ms 阶梯 | `FeedPage.tsx:472-483` | 会在登场之外再淡入一遍 | `phase !== "idle"` 时不给 `.rise` 类（或把 `animationDelay` 设为 0） |
| `motion.div layout="position"`（T5） | `FeedPage.tsx:454-485`，`layoutOn` 在 :158 | 收场时会同时做位置补间，卡片会"边缩边滑" | 演出期间 `layoutOn=false` |
| 加载态 `opacity-55` | `FeedPage.tsx:445-452` | 会把整场演出压暗 | 进入 `collapsing` 前先置 1 |
| 结果态状态条 | 本方案 L2 | 与"看新内容"胶囊职责重复 | 有演出时文案改成"刚放进来的 N 条"，不再给入口 |

### 5.7 降级路径（同一份数据，三档表现）

| 场景 | 表现 |
| --- | --- |
| 顶部 + 新增 ≥ 3 + 无减弱偏好 | 完整清场登场（0.8–1.25s） |
| 顶部 + 新增 1–2 条 | 轻量档：不收起，只让这 1–2 张就地 pop + 标记 |
| 已滚到列表中部/底部 | 不动列表，顶部浮「有 N 条新内容」胶囊；点击回到顶部后再播（此时用户已主动接受跳转） |
| 新增 0 / 全冷却 / 失败但无新条 | 不播；状态条给结果与处置 |
| reduce-motion / 窄屏 / 隐藏页 | 不播；数据直接切换，读屏照常播报 |
| 演出中用户滚动、按方向键、切标签页 | 立刻结算到终态（`settle()`），不补播 |

### 5.8 无障碍与性能

- 列表容器演出期间 `aria-busy="true"`；开演播报一次「刷新完成，新增 42 条」，**不要逐卡播报**。
- 新卡标记是纯装饰：`aria-hidden="true"`，差异靠播报里的数字，不靠视觉徽标。
- 30 张卡 × 2 个属性（transform/opacity）为 GPU 合成层动画；不要在收场里改 `height/padding/margin`。
- 兜底定时器保证「隐藏页/掉帧/中途报错」下 1.7s 内一定回到 `idle`，不会永久 `aria-busy`。
- 与 `nav.ts` 的 `vt-running` 滚动锁互斥：刷新演出不加滚动锁（用户必须能滚，且滚动即结算）。

## 6. 后端契约补充（都很小）

1. `RunState` 加 `phase`（§3）与 `market`（`service.py` 已写，`api.ts:64-75` 没声明）。
2. `plugins[pid]` 加 `new_count` 与 `label`：
   - `new_count`：`onefeed/store.py:384-399` 的 `upsert_items` 只返回受影响行数，分不出新增/更新。在 `_run` 里先 `existing = store.item_ids(ids)`，再 `new = len(set(ids) - existing)`，约 5 行。
   - `label`：平台展示名，免得前端再维护 id→名字映射（现在散在 `TabRail.tsx:539-542`）。
3. `POST /api/refresh` 的 409 已带 `code: "refresh_running"`（`api.py:899-910`），前端据此在状态条标「已经在跑了」，不弹 toast。
4. 最近一轮 snapshot 已在 `_state`，页面刷新后首屏读一次 `/api/progress` 就能恢复「上一轮 +42 条（12:31）」。
5. 动效本身**不需要后端新字段**：新卡判定走前端 id diff。`new_count` 只用于结果态文案。

## 7. 容易翻车的细节

- **状态条高度**：`min-h-[40px]` + 单行 flex + truncate；任何状态下 `scrollHeight` 前后差必须为 0（验收项）。
- **别用 exit 动画收场**：见 §5.4；相位只能靠定时器推进。
- **高度锁必须加**：不加就会在收场瞬间把页面下方的内容往上拽，并可能夹 `scrollY`。
- **演出期禁用 `.rise` 与 `layout`**，否则一卡两动画。
- **轮询粒度** 1600ms 对单平台 2–8s 够用；要更实时，把 `/api/progress` 序列化挂 SSE，不必新建端点。
- **不要两处说同一件事**：有状态条结果态就降级结束 toast，否则 toast 会盖住 AI 输入条（历史上 `bottom-6` 重叠过）。
- **失败重试按平台**，不整轮重跑，否则冷却中的平台又被跳过。
- **顶栏计数**（`TopBar.tsx:59-61` 的「924 条」）在结果态后跟着 `health` 刷新。
- **缓存种子**：`useFeed` 会先用缓存渲染（`api.ts:966` 的 `feedCache`），触发判定的 effect 必须等 `loading` 结束，否则会把缓存当"新数据"播一遍。

## 8. 实施批次（约 2.5–3 天）

| 批次 | 内容 | 估时 |
| --- | --- | --- |
| R1 | 后端 `phase` + 类型补全；L2 进行中态（pill 四态、已用秒数）；L1 移动端 3/7、按钮不禁用 | 半天 |
| R2 | 结果态 + 按平台失败重试 + 冷却/强制抓取；`refreshSeq` 信号 | 1 天 |
| R3 | 清场登场：`REVEAL` 常数、相位状态机、高度锁、旧卡逆序收、新卡逐个 pop、新卡标记、降级三档、兜底定时器、与 `.rise`/`layout` 的解耦 | 1 天 |
| R4 | `new_count`/`label`、读屏播报、demo 文案、reduce 降级、结束 toast 合并进状态条；胶囊兜底入口 | 半天 |

先做 R1（半天就能消掉「完全没反应」）；R3 依赖 R2 的 `refreshSeq`，不要提前。

## 9. 验收清单

1. 点刷新 1s 内出现状态条；页面 `scrollHeight` 前后差 = 0。
2. 平台 pill 按真实顺序「排队 → 抓取中 → ✓ 12」；结束显示总数与失败数。
3. 采集期间滚到列表中部：列表不被顶动、`scrollY` 不变。
4. 顶部刷新且新增 ≥ 3：旧卡逆序收起（≤400ms）→ 留白 → 老卡整组淡入 → 新卡逐个 pop；全程 0.8–1.25s，`scrollY` 不变，页面下方元素不位移。
5. 新卡有「新」标记，2.4s 后消失且不引起布局变化；老卡不重播 pop。
6. 新增 1–2 条时走轻量档（不收场）；已滚到中部时走胶囊，不播。
7. `sort=热度` 且前台无新条：不播，结果态给「切到最新看新内容」。
8. 演出中滚轮/方向键：立即结算，不补播、不卡 `aria-busy`。
9. reduce-motion：无动画，读屏仍播报「新增 N 条」。
10. 隐藏标签页触发：无残留 `aria-busy`、无永久 minHeight。
11. 单个平台失败可展开 error；「重试这个平台」只出现该平台请求。
12. 全冷却点刷新：给最早可抓时间 + 强制抓取（二次确认后 `force:true`）。
13. 320px 宽：状态条单行不换行、不重叠。
14. `npm run build`、`pytest`、`node scripts/check-ui.mjs` 全绿。

## 10. 明确不做

- 全屏 loading / 遮罩：丢上下文，且与「反感整页位移」直接冲突。
- 刷新时清空列表：等于把用户正在看的东西拿走；本方案是"收起后立刻放回"，不是清空。
- 演出期间锁滚动（`nav.ts` 的 `vt-running` 那套）：刷新动效必须让用户随时能打断。
- 假的「预计剩余时间」。
- 让每张卡订阅 `/api/progress`：走 `ctx` 单点分发。
- 为刷新单独做一套 SSE。
- 用 `AnimatePresence` 的 exit 做收场（见 §5.4）。

## 11. 最小可行版（如果只能改一处）

在 L2 位置加一条**固定高度**的「正在抓取 3/7 · 抖音 · 已 18s」，数据全部来自已有的 `plugins`——不动后端，约 80 行，把「点了没反应」变成「看得见在跑」。

第二小步（约 120 行，不含后端）：只做 `refreshSeq` + 新卡 `card-pop` + `data-in` 标记，不收起旧卡。它能先解决"看不出哪些是新的"，也验证了 `refreshSeq` 与 id diff 这两块地基；之后再上完整清场登场。
