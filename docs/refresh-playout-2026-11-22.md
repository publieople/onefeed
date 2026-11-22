# 刷新演出落地记录（2026-11-22）

目标：让「刷新」从「图标转、底部弹个提示」变成看得见的一段演出——旧一屏收下去，新的那条一张张弹出来；人在列表深处时改成打胶囊，不拆屏。

方案在 [docs/refresh-ux-2026-11-22.md](refresh-ux-2026-11-22.md)（§5 是演出时间轴）。本文只记落地后的事实、踩到的坑和验证数字。

## 1. 四处关键实现

### 1.1 相位机（web/src/pages/FeedPage.tsx）

`idle → collapsing → waiting → revealing → idle`，只有 `ctx.refreshSeq` 变化才开演：

| 闸门 | 代码 | 为什么 |
| --- | --- | --- |
| 序号未变 | `if (ctx.refreshSeq === playedSeq.current) return;` | `reloadKey` 还会被换筛选、收藏、bump 改动 |
| 数据未到 | `if (feed.loadedKey !== ctx.reloadKey) return;` | 序号一到就演会拿一屏旧卡开演，最后什么都没登场 |
| 无新增 | `if (freshNow.length === 0) return;` | 空跑一轮不该有演出 |
| 关动效 | `if (reduceMotion) return;` | 硬闸门 |
| 窄屏 | `matchMedia("(max-width: 639px)")` | 手机上清场等于清空，直接不演 |
| 后台页 | `document.visibilityState !== "visible"` | 回来时看到的是半截动画 |
| 刚换过筛选 | `Date.now() - lastQueryAt.current < 1200` | 别把「换条件」误当「刷新」 |
| 人在深处 | `top < -window.innerHeight * 0.6` | 拆屏比换内容更烦，改胶囊 |

五拍：收（200ms/张、逆序 18ms 间隔、cap 12）→ 留白 60ms → 老卡整组 160ms → 新卡 pop 300ms（45ms 间隔、cap 12）→ 结算。数字全在 `web/src/motion/tokens.ts` 的 `REVEAL`，组件里不写魔法数。

三个不能省的保险：
- 高度锁：开演前量 `grid.getBoundingClientRect().height` 写 `minHeight`，收场时网格不许缩；
- 不用 exit 动画：只靠 `setTimeout` 摘节点，再加 `setTimeout(settle, ms + 400)` 兜底（动画帧被节流的机器上，`onAnimationEnd` 永不到）；
- 滚动即取消：`wheel / touchmove / keydown` 一律 settle，不锁滚动。

### 1.2 收起的是「刷新前那一屏」

`preRefreshIds.current` / `preRefreshItems.current` 在序号变化时（声明在开演 effect 之前，保证先跑）冻结当时 DOM 里的 18 张卡；开演时 `setOldItems(preRefreshItems.current)`。

第一版直接 `setOldItems(feed.items)`，结果收起的是 23 张（含新卡）：新内容还没登场就先被收了一遍，语义是反的。

### 1.3 useFeed 汇报 `loadedKey`（web/src/api.ts）

`reloadKey` 只是「我请求了」；`loadedKey` 是「这轮数据真的落进 items 了」，在 load 的 finally 里 `if (!append) setLoadedKey(keyRef.current)`。

没有它时探针实测：`__gate = {seq: 1, total: 1, loading: false, item: 18, phase: "idle"}` —— 闸门全过、items 还是旧 18 条，轻量档因此空演（`peak_new: 0`、按钮停在「看新内容」）。

### 1.4 played 不能由 inShow 推

状态条「刚放进来的 N 条 → 2.6s 后 freshIds 归零 → 按钮又变回『看新内容』」，点一下把同一批再演一遍。改用独立 `played` state，在本轮开演时置真、序号再次变化时置假。

## 2. new_count 真机 bug（后端）

第一次真机刷新：拉回 78 条、库 1155→1220（+65），状态条却写「这一轮 +0 条」。

根因：`onefeed/service.py` 用 `isinstance(it, dict)` 取 id；而 `plugin_runtime/host.py:176 def pull(...) -> list[Item]` 返回的是 `Item` 对象，只有演示模式给 dict。于是 `known` 恒空、`fresh` 恒 0。

修法：`def _item_id(it: Any) -> str`（dict 取 `get("id")`，否则 `getattr(it, "id", "")`），配合新加的 `Store.item_ids(ids)`（分块 400 查，避开 SQLite 变量上限），入库前后各算一次集合差。修复后真机：+21 → +46 都对。

## 3. 验证

- `uv run --with pytest python -m pytest tests -q` → **151 passed**；`cd web && node scripts/check-ui.mjs` → 无违规；`npm run build` → index-BStHkGsc.js 463.77 kB。
- `probes/probe_playout.py`（Playwright 拦 `/api/feed`、`/api/progress`、`/api/refresh` 造「一轮 +5 条」；headless 的 `visibilityState` 默认 hidden，探针把它覆写成 visible 才能测）。

| 场景 | 关键数字 | 结论 |
| --- | --- | --- |
| 在顶部刷新 | out=18 持续约 570ms → out=0 / freshNew=5 / carry=18 / cards=23；`BEFORE_TOP 277.125` 前后不变 | 清场→登场成立；网格顶没动，页面不跳 |
| 只新增 1 条 | `peak_out 0, peak_new 1, lock ""` | 走轻量档，不清场 |
| 滚到 2400 再刷新 | `PILL_DID_NOT_COLLAPSE True`、胶囊「有 5 条新内容」、点它 `scrollY 0` 且补播 `peak_new 5` | 深处不拆屏，胶囊是保底入口 |
| 演完再按状态条 | `BAR_AFTER_SHOW played` | 不会重播同一批 |

## 4. 踩过的两个坑

1. **web/dist 的 base**：一次 `VITE_BASE=/onefeed/` 的项目页构建覆盖了 dist，本地 8799 直接白屏（HTML 引用 `/onefeed/assets/…`，模块 MIME 变 text/html）。本地服务读的是 `web/dist`，base 必须是 `/`；发现 hash 对不上先比对 `dist/index.html` 与实际 asset。
2. **headless 看不到演出**：CDP 拉起的标签页 `visibilityState === "hidden"`，闸门按设计跳过演出。要在自动化里验证必须覆写该属性，否则会误判成「坏了」。

## 5. 已知边界

- 演出只在「刷新完成且有新增」时出现；换筛选、返回、收藏仍是原来的 layout 动画，互不叠加。
- 窄屏（≤639px）默认不演，只有胶囊。
- 浏览器后台标签页里完成的刷新，回到前台时直接是新内容，不补演。
- 本仓库工作树里另有 012-demo-site 的在建改动（`web/src/demo.ts`、`scripts/export_demo.py` 等），本次提交只含刷新演出相关文件，未碰它们；`web/dist` 因此留在工作树未提交，等那边收尾后一并重建。
