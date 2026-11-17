# 008 主题与暗色模式

日期：2026-11-17
状态：已实现

## 1. 变量表

所有颜色走 CSS 变量，`tailwind.config.js` 里映射成 `rgb(var(--c-*) / <alpha-value>)`，所以 `bg-paper/60` 这类透明度写法仍然有效。

| 变量 | 亮色 | 暗色 | 用途 |
| --- | --- | --- | --- |
| `--c-ink` | 23 23 26 | 232 234 238 | 正文 |
| `--c-muted` | 90 92 99 | 154 158 168 | 次要文字 |
| `--c-fade` | 140 143 152 | 116 120 130 | 提示、占位 |
| `--c-line` | 232 232 235 | 44 48 56 | 描边、分隔线 |
| `--c-paper` | 255 255 255 | 15 17 21 | 卡片与页面底 |
| `--c-wash` | 246 246 247 | 24 27 32 | 内嵌块、骨架、输入框 |
| `--c-solid` | 23 23 26 | 240 241 245 | 实底按钮背景 |
| `--c-solid-fg` | 255 255 255 | 17 19 23 | 实底按钮文字 |
| `--shadow-card` | `0 1px 2px rgba(20,22,28,.05)` | `0 1px 2px rgba(0,0,0,.5)` | 卡片 |
| `--shadow-pop` | `0 8px 30px rgba(20,22,28,.12)` | `0 10px 40px rgba(0,0,0,.6)` | 浮层 |

语义色 `solid` / `solid-fg` 是这一版新加的：之前实底按钮写死 `bg-ink text-white`，暗色下 `ink` 变浅，白字就糊了。

## 2. 切换与持久化

- `web/src/theme.ts`：`currentTheme()` 读 `html.dark`；`applyTheme(next)` 切 class、写 `localStorage['onefeed.theme']`、同步 `<meta name="theme-color">`（亮 #ffffff / 暗 #0f1115）；`initialTheme()` 存过用存的，否则跟系统 `prefers-color-scheme`。
- `web/index.html` 头部内联脚本在首帧前就把 `dark` 类打上，避免刷新时先白一下。
- 顶栏右侧 Sun/Moon 按钮负责切换，`aria-label` 随当前主题变化。
- `theme.css` 里 `color-scheme` 跟主题走（滚动条、表单控件、原生弹窗跟着变），`body` 的背景与文字加 0.24s 过渡。
- `prefers-reduced-motion` 下所有动效降到 0.01ms，主题切换瞬间完成。

## 3. 暗色例外的三类

1. **平台色底上的白字**：B 站粉、小红书红、抖音黑这些色块里的文字始终是白的，不能跟着 `ink` 翻转。静态门禁 `text-white` 规则对这类做了豁免（附近有 `bg-paper/` 或 `style=` 时放行）。
2. **图片与视频遮罩**：封面上的时长角标、播放按钮一律黑底白字，与主题无关。
3. **状态色**：`emerald` / `amber` 的浅底深字在暗色下不可读，统一补 `dark:bg-*-500/10 dark:border-*-500/30 dark:text-*-300`。涉及 `AiProviders.tsx`、`ItemPage.tsx`、`MarketPage.tsx`、`SettingsPage.tsx`。

## 4. 验证

- 亮/暗两套信息流、暗色设置页、暗色 B 站详情页截图存 `design/feed-light.png`、`design/feed-dark.png`、`design/settings-dark.png`、`design/detail-dark.png`。
- 行为门禁覆盖：点主题按钮后 `html.dark` 出现、localStorage 写入、刷新后保留（`probes/check_interactions.py`）。
- 浏览器实测细节：切换后 `color-scheme` 与 meta theme-color 同步；暗色下骨架 shimmer、AI 面板、保存条均正常。
