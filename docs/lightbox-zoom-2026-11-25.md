# 图文灯箱：从缩略图缩放展开（2026-11-25）

## 1. 改前

点开小红书 / B 站的图文缩略图时，大图是直接跳出来的，关掉也是直接消失。看起来像换了一张图，而不是同一张图被放大。

两个原因叠在一起：

- `web/src/pages/ItemPage.tsx` 里灯箱大图常驻 `viewTransitionName: "of-lb"`，缩略图在点击时也挂同一个名字。新快照里同时存在两个 `of-lb`，浏览器会判定重名，整段共享元素转场降级成普通根转场。
- `web/src/theme.css` 里根本没有 `of-lb` 的 group / old / new 规则。即使名字有效，也只是一次默认的整页淡入，不会有缩放。

关闭时同样重名：灯箱大图还没卸载，缩略图又被挂上 `of-lb`。

## 2. 做法

### 2.1 名字交接，而不是常驻

灯箱大图不再常驻名字，改成 `data-lb-image` 标记：

```tsx
<img data-lb-image="" ... />
```

打开时：

1. 点击的缩略图在快照前挂上 `of-lb`；
2. React 提交新 DOM 后，`afterApply` 把缩略图的名字摘掉，再把名字交给新挂载的灯箱大图；
3. 转场结束的 `after` 把两端都清干净。

这样旧快照里只有缩略图，新快照里只有大图，两端各一个 `of-lb`。

关闭反过来：快照前只给大图挂名，`afterApply` 在大图卸载后把名字交给缩略图。关闭调用的是 `runNav("back", ...)`，不是 `"lightbox"`——只有 back 这一组才会让大图快照留在场上缩回去。

`web/src/motion/nav.ts` 为此新增了 `afterApply` 钩子：它在 `flushSync(apply)` 之后、新快照之前执行，专门处理这种「同一棵树里两端换边挂名」。钩子抛错会被吞掉，最坏只是少一段动画，不影响开关灯箱。

### 2.2 动画曲线

`web/src/theme.css` 新增：

- group：`z-index: 6`，打开 0.42s `cubic-bezier(0.16, 1, 0.3, 1)`，关闭 0.34s `cubic-bezier(0.22, 1, 0.36, 1)`；
- 打开：旧快照隐藏，新快照跑 `nav-lb-in`（透明度 0.7 → 1）；
- 关闭：旧快照跑 `nav-lb-out`（透明度 1 → 0），新快照隐藏。

盒子尺寸和位置由 View Transition 的 group 负责补间，透明度只负责让交接不突兀。

## 3. 验证

测试环境用 ego-browser，把 `of-lb` 的 group / old / new 动画临时改成 2 秒，再点击和关闭，采样 `document.getAnimations()`：

- 打开 117ms：`img=of-lb`、`thumb=none`，`::view-transition-group(of-lb)` 2000ms，`::view-transition-new(of-lb)` 跑 `nav-lb-in`；
- 打开 1111ms：同一组动画仍在跑；
- 关闭 73ms：`img=null`、`thumb=of-lb`，`::view-transition-old(of-lb)` 跑 `nav-lb-out`，2000ms；
- 关闭 1084ms：仍在缩回；
- 结束后两端名字都清空，`document.getAnimations()` 为空。

截图（2 秒慢速）：

- 打开：`.onefeed/tmp/lb-open-0.png` → `lb-open-400.png` → `lb-open-1100.png`，大图从缩略图大小逐帧长到整屏，最后出现灯箱顶栏「1/2」与关闭按钮；
- 关闭：`.onefeed/tmp/lb-close-0.png` → `lb-close-650.png` → `lb-close-end.png`，大图从整屏缩回左下缩略图，最后回到双图网格。

生产时长没有放大，仍是 0.42s / 0.34s，所以实际观感是短促的缩放，不是慢动作。

守门测试：`tests/test_lightbox.py` 共 16 项，覆盖「大图不常驻共享名」「打开时名字交给大图」「关闭时名字交回缩略图」「关闭走 back 反向组」「灯箱有缩放曲线」。

构建：`index-ReXtV0o-.js` 479.14 kB / gzip 152.11 kB，`index-DUGfbJN7.css` 58.55 kB，`ItemPage-Bzud3oXa.js` 69.37 kB。

## 4. 边界

- 用户开了「减少动态效果」（`prefers-reduced-motion: reduce`）时，`runNav` 直接 `apply()`，灯箱仍是瞬时切换。这是有意保留的系统偏好，不是漏做。
- 缩略图是 `object-cover` 的 4:5 小盒，灯箱大图是 `object-contain` 的整图。共享元素补间的是外盒，图片本身仍按各自比例绘制；比例差很大时，过渡中会看到一次轻度的画面内容重排，而不是同一像素被拉伸。
- 只对图文 Gallery 生效。视频封面、头像等没有接 `of-lb`，它们走各自的页面跳转转场。
