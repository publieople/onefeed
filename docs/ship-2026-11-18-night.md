# 今晚交付：六件事全做完（2026-11-18 夜）

对应方案：`docs/plan-next-2026-11-18.md`。下面按「你明早怎么验」组织，不按我干活的顺序。

## 先起来

```powershell
cd E:\Documents\deepseek-harness\default-workspace\onefeed
.venv\Scripts\python.exe -m onefeed --demo --no-browser --port 8799
```

打开 <http://127.0.0.1:8799>。前端产物已重建（`web/dist` 里是新的 `index-DyWE4cEx.js`），后端 8799 上跑的就是这份。

自检全绿：`uv run --with pytest python -m pytest tests -q` → **50 passed**；`cd web; node scripts/check-ui.mjs` → **没有违规**；`npm run build` → 455.86 kB（gzip 147.78 kB）。

## 六件事，逐条验

### 1. 共享元素转场（T1–T6）

点任意卡片：媒体框从卡片位置长成详情页的 hero，标题跟着迁移，返回时缩回原卡片。

- 中键 / ⌘+点击 / 右键「在新标签页打开」现在都能用（卡片是真 `<a href="/item/...">`，`web/src/components/Card.tsx:230`）。
- 连点两张卡片：第二次直接瞬切，不会卡死（`web/src/motion/nav.ts` 的 `inflight` 令牌）。
- 顶栏独立成层，不跟整页一起飞（`::view-transition-group(of-topbar)`）。
- 详情页「AI 总结 ↔ 原文」切 tab：**播放器不再重新加载**（媒体区提到 tab 之上常驻，`web/src/pages/ItemPage.tsx` 的 `showHero`）。
- 换筛选 / 排序：留下来的卡片会滑到新位置，但只在 ≤12 张时开（项数多时逐张滑像拖地，超出就直接换）。
- 返回落点：`restoreAnchor` 会等数据到位、图片撑高后再对齐，不再只找一次。

> 注意：本机 headless Chrome 的 `document.visibilityState` 是 `hidden`，浏览器规范要求此时跳过 View Transition，所以**动画本身我只验证了结构与日志**，肉眼看效果得靠你正常窗口打开。Firefox / `prefers-reduced-motion` 走的是直接跳转，功能不受影响。

### 2. AI 总结流式

点开一条没缓存过的条目（比如刚刷新进来的），1–2 秒内出现「Agent 正在看这条内容… 2s」+ 四行骨架，然后要点逐条往外吐。

- 模型先吐思维链时显示「Agent 正在通读素材…」，正文一开始就切成逐字流。
- 只拿到标题和简介时会带「注意：只拿到标题和简介，结论可能不完整」。
- 失败有「再试一次」，不会白屏。

### 3. 输入框动效 + 键盘模型

- 输入框**点一下才展开**（以前 focus 一下就弹面板，还铺一层透明遮罩把信息流的第一次点击吃掉——这是上一轮评审的 P0，现在没了）。
- 聚焦时整条放大 1.2%、上移 1px、边框变深，左侧图标轻微旋转；展开时圆角从胶囊变卡片；占位提示每 4 秒换一句。
- `⌘K` / `Ctrl+K` 或 `/`：在任何页面直接唤起。`Esc` 收起（**立即**收起，不等退场动画）。点面板外面也收。
- 面板是真正的 `role="dialog" aria-modal="true"`：Tab 在面板内循环，关掉后焦点还给输入框，AI 回复区 `aria-live` 读屏能播报。
- 列表键盘：`j`/`k` 上下、`h`/`l` 跨列、`Enter` 打开、`o` 新标签、`?` 快捷键表、`t` 切主题、`r` 刷新。
- 平台胶囊：`←`/`→`/`Home`/`End` **只挪焦点不改筛选**（以前按一次发一次 `/api/feed`），`Enter`/`Space` 才选，`Esc` 退回「全部」。轨道滚动时两侧有渐隐，能看出后面还有平台。
- 空态按钮按原因分流：筛出 0 条给「清空筛选条件」，不再给一个没用的「刷新」。

### 4. 停止按钮（真停）

发送键在 AI 跑起来后变成方块「停止」。点下去：

1. 按钮变「正在停止」，8 秒兜底（后端不回应也不会卡在忙态）；
2. 后端 `_run_action` / `_await_confirm` 的检查点抛 `Cancelled`，**工具不再继续执行**（实测 steps=0，即模型刚发工具调用就被拦住）；
3. 前端落一条「停下了，先把翻到的 N 条留给你」，轨迹里写「已按你的要求停下」，AI 回复下方有「按你点的停止收的尾」小胶囊。

以前是：后端只是置了个没人读的 flag，agent 继续跑、继续写数据；前端还报「事件流断了」。

### 5. 破坏性操作确认

| 位置 | 现在 |
|---|---|
| 设置 · 清除所有 key | 要逐字输入 `CLEAR` 才能点「清除」，说明 AI 会退回本地规则解析 |
| 设置 · 退出登录 | 说明会删本机 cookie、要重新扫码 |
| 设置 · 恢复默认值 | 说明会连带丢掉没保存的改动 |
| 市场 · 卸载插件 | 说明会删本机插件目录；**卸载后 5 秒内可撤销**（实测 DELETE → 点撤销 → POST install → 插件回来了） |
| AI 助手 · 删模型行 | 已填 key 时提示「key 会一起删掉」 |

配套修的三个坑：

- 插件开关以前**假成功**（不看响应码，失败也说「已启用」）——现在乐观更新 + 失败回滚 + 行内原因。
- `clearKeys` 之后 baseline 被写成空串，导致 `dirty` 恒假、保存条再也不出现——已修，并加了 `beforeunload` 拦截。
- 市场页原来共用一个 `busy` 字符串，同时装两个插件 spinner 会互相覆盖——改成按插件 id 各自 pending。

## 结构上新增了什么

| 文件 | 作用 |
|---|---|
| `web/src/motion/tokens.ts` | 全站动效唯一真源（时长、曲线、弹簧）。`motion.ts` 改成 re-export，老引用不用动 |
| `web/src/motion/nav.ts` | `runNav(kind, apply, {names})`：push/back/tab/lightbox/filter/plain，最多三个共享元素，并发令牌，`vt-running` 滚动锁 |
| `web/src/components/ui/Confirm.tsx` | `confirmDialog()` + `<ConfirmHost/>`：焦点陷阱、Esc、遮罩点击、危险色、打字确认 |
| `web/src/motion/useHotkeys.ts` | 作用域快捷键（global / list / dialog），输入框内与 IME 期间自动让位 |
| `web/src/motion/useAction.ts` | `useAction` / `useBatchAction`：每个 key 独立 pending |
| `web/src/components/ShortcutHelp.tsx` | `?` 打开的快捷键表（也是键位的文档） |
| `web/src/pages/NotFound.tsx` | 以前访问错地址只剩顶栏，现在有 404 和「回到信息流」 |

后端：`onefeed/agent_runtime.py` 新增 `Cancelled` 与取消检查点、`cancelled` 事件；`onefeed/api.py` 的 cancel 接口只置位、由跑着的线程自己收尾；`sse_stream` 在收尾前再 drain 一遍，避免 done/cancelled 帧丢失。

## 测试

- 重写 `tests/test_nav_motion.py`：锁 `of-media` / `of-title` 契约、0.42s + expo-out、`of-card` 必须不存在、并发保护、顶栏独立层、卡片是链接、详情页 hero 常驻。
- 新增 `tests/test_interaction.py`：快捷键作用域、胶囊方向键不改筛选、输入框不再 focus 即开、弹层不依赖退场动画、dialog 语义、五处确认、按 id pending、baseline/beforeunload、空态分流、列表键盘。

## 还没做 / 已知限制

1. **真机窄屏没测**：手机上设置页的目录（`hidden lg:block`）仍然只有桌面有，胶囊的多选也只能靠 Ctrl/Shift（提示写在 `aria-label` 里，视觉上没露出来）。
2. **Firefox 降级路径没真机跑**：无 `startViewTransition` 时是直接跳（不报错），方案文档里写的「240ms 交叉淡入」没做。
3. **转场动画无法在 headless 里目视**（见上），我只验证了：两个共享元素挂着正确名字、`html.nav-vt` 类在、`vt.finished` 后清理干净、连点不卡。
4. **T5 只在 ≤12 项时开**，超过就是直接换；如果你觉得应该全量开，改 `web/src/pages/FeedPage.tsx` 的 `animateLayout` 一行。
5. 市场「撤销」只覆盖卸载，安装/更新没有撤销（安装失败会提示原因）。

## 明早建议先看这三处

1. **点一张卡片再返回**——这是这次改动的门面，媒体框和标题的连续性是重点。
2. **发一句 AI 请求然后点停止**——看它是否立刻停在「已按你的要求停下」，而不是转圈到结束。
3. **设置页「清除所有 key」**——确认弹窗的措辞和打字确认是否合你的口味。

哪块觉得不对味，告诉我具体是哪个动作，我按动作改，不动别的。
