# 抖音推荐流：实测结论与采集机制（2026-11-13 本机验证）

## 一句话
抖音的登录态推荐流**不用碰签名**——用 Playwright 驱动系统 Chrome 打开 www.douyin.com，监听 `/aweme/v2/web/module/feed/` 的响应体，`aweme_list` 里就是完整视频对象。已在本机跑通，**免登录即拿到 20 条**（含封面、点赞、评论数、share_url）。

## 为什么 dy-cli 的 `get_feed()` 走不通
1. **接口换代**：dy-cli 里写死的是 `/aweme/v1/web/tab/feed/`；抖音前端现在走 `/aweme/v2/web/module/feed/`（`module_id=3003101`、`refresh_index`、`pull_type`、`count=20`）。
2. **三件套签名**：feed 类接口在服务端校验 `a_bogus`（bdms / JSVMP，SM3 + RC4 + 自定义 base64）+ `timestamp` + `x-secsdk-web-signature`（secsdk）。缺任一个 → 403 Sign Invalid。且 cookie 必须与签名密钥来自同一浏览器会话（uifid 由 `web_runtime_security_uid` 派生）。dy-cli 的 `get_feed` 只传 `get_base_params()`，一个签名都不带，所以返回「空响应」。
   - 参考：github.com/mafqla/douyin-api/blob/main/docs/sign_reverse_findings.md（2026-06）、github.com/hanzheng1954/douyin-abogus-analysis（2026-08 完整逆向，Python 移植版）
3. 结论：自己造签名 = 每周跟版本，2 周黑客松项目不该背这个。

## 实测通过的机制（已跑通 4 次）
```
系统 Chrome（C:\Program Files\Google\Chrome\Application\chrome.exe）
  → Playwright launch(executable_path=..., headless=False)
  → goto https://www.douyin.com/   （未登录会 302 到 /jingxuan 精选页，同样出流）
  → page.on("response") 过滤 URL 含 "/aweme/v2/web/module/feed/"
  → resp.json()["aweme_list"] → 每条 10~20 个 aweme
  → 滚动 page.mouse.wheel(0, 3000) 触发下一页
```
实测产出：首次加载 1 页 20 条；滚 3 次共 2 页 / 40 原始 / 20 去重（同一 `refresh_index` 会重复下发）。

### 规范化后的字段（全部可用）
| OneFeed 字段 | 抖音字段 |
|---|---|
| id | `aweme_id` |
| title | `desc`（含话题标签） |
| author / author_id | `author.nickname` / `author.sec_uid` |
| cover | `video.cover.url_list[0]`（或 `origin_cover`，是带签名的 douyinpic CDN 链，可直接 img src） |
| duration | `video.duration`（毫秒） |
| published_at | `create_time`（秒级 unix） |
| like / comment / share | `statistics.digg_count` / `comment_count` / `share_count`（`play_count` 恒为 0，web 端不下发） |
| url | `share_info.share_url`（iesdouyin 分享链，或自拼 `https://www.douyin.com/video/{aweme_id}`） |
| raw_id_type | 抖音 aweme_id 是数字串，B 站是 bvid，小红书是 note_id → 需 `Item.id` 带平台前缀 |

## 接登录态
- 复用 dy-cli 的登录：`dy login` 扫码后 cookie 落在 `C:\Users\Publieople\.dy\cookies\default.json`，读出来 `ctx.add_cookies()` 注入即可，一次扫码三处共用（CLI 搜索/评论 + 浏览器推荐流）。
- 或专用持久 profile：`launch_persistent_context(user_data_dir=".onefeed/dy-profile")`，首跑在那个窗口里扫码，之后免登。
- 注入 cookie 后同一个 URL 返回的就是**按账号个性化**的流，代码零改动。

## 坑（都踩过）
1. **headless 会被降级**：`headless=True` 时首页落到 landing 选择页，`document.body.innerText` 只有 1573 字，0 个视频链接，feed 响应只回 2~6 条空壳。必须 `headless=False`。
2. **别用 `channel="chrome"`**：Playwright 会去 `%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe` 找，实际装在 `C:\Program Files\...`，直接报 `Chromium distribution 'chrome' is not found`。用 `executable_path` 指向 exe。
3. **代理变量**：本机 `NO_PROXY` 含 `[::1]` 会让 httpx 崩（`invalid literal for int() with base 10: ':1]'`），spawn 子进程时传干净 env。
4. **`#RENDER_DATA` 不可靠**：精选页虽然有 212KB 的 SSR 载荷，但里面只有壳（`app` 一个 key），视频数据全靠 XHR。所以只信 response hook。
5. **评论同样走浏览器**：`/aweme/v1/web/comment/list/` 在页面里点开评论面板就会发，抓 response 比 `dy comments`（要登录）更稳，还能顺带拿到二级回复。

## 方案对比（黑客松视角）
| 方案 | 稳定性 | 成本 | 字段 | 评价 |
|---|---|---|---|---|
| 浏览器回放（本方案） | 高（页面改版只影响选择器/URL 片段） | 低（Chrome 已有，Playwright 随 dy-cli 装了） | 全（封面/互动/作者/评论） | ✅ 主用 |
| dy-cli + 自造 a_bogus | 低（三件套 + 每周跟版） | 高 | 中 | ❌ 不做 |
| 第三方签名服务（52jan 等） | 中（服务挂/额度/封号） | 低 | 全 | 备选，路演不用 |
| 抖音开放平台 | — | — | 无推荐流 | ❌ 不开放 |
| 免登录热榜 `dy trending` | 高 | 低 | 只有热搜词 + 封面 | 兜底（比无好，比有个性化流差很多） |

## 建议的 adapter 形状
```python
# adapters/douyin_browser.py
class DouyinBrowserAdapter:
    """常驻一个 Playwright 会话；每次 pull() 触发一次滚动，收集新 aweme。"""
    def __init__(self, profile_dir, headless=False): ...
    def warmup(self):            # 首跑：开窗、等登录/takeover
    def pull(self, limit=20) -> list[Item]:   # 滚动 + 收 response + 去重 + 规范化
    def comments(self, item, limit=20) -> list[Comment]:  # 点开评论面板抓 comment/list
```
- 单次 pull 延迟 6~9s（首帧最慢），结果缓存 10 分钟；滑动节流 3s，别把账号刷成风控。
- **演示兜底**：未登录也能出流（精选页），所以路演当天即使 cookie 失效，页面照样有内容 —— 这点比热榜强很多。
---

## 落地结果（2026-11-13 20:40 实测，`adapters/douyin_browser.py`）

上面的骨架已经写成可跑的代码，实测数据：

| 项 | 结果 |
|---|---|
| 首屏 | 一次 `pull()` 收到 20 条（buffer 累计 58~59 条，含滚动追加） |
| 字段完整度 | `comment_count` 8/8 非零，封面是可直接 `<img src>` 的 douyinpic 直链 |
| 评论 | 视频页自动发 `https://www-hj.douyin.com/aweme/v1/web/comment/list/`，首页 5 条热门 + `reply_comment` 二级回复 |
| 登录态 | 读 `~/.dy/cookies/default.json`（Playwright storage_state 格式），`ctx.add_cookies()` 注入 |

### 实现时又踩到的三个坑

1. **这个版本的 `launch_persistent_context()` 不收 `storage_state` 参数**，传了直接
   `TypeError: BrowserType.launch_persistent_context() got an unexpected keyword argument 'storage_state'`。
   正确做法：先建 persistent context，再 `ctx.add_cookies(json.load(...)["cookies"])`。cookie 里可以带 `domain/path/httpOnly/secure/sameSite`，Playwright 原样吃。
2. **首帧延迟不稳定（3~15s）**：第一次跑成功，第二次 9 秒内一条响应都没有。修法是轮询 + 前滚 + 一次 reload：
   `_await_feed(rounds=6, step=settle_ms)`，第 3 轮还没响应就 `page.reload()`。pull 里再兜一层，仍空就抛明确错误（提示页面可能停在验证页）。
3. **精选页缺评论数**：落到 `/jingxuan`（未登录时常见）的那一版 module feed，`statistics` 里没有 `comment_count`，8 条全是 0；
   落到 `https://www.douyin.com/` 主推荐页时统计齐全（♥14036 💬181 ↪270 这种）。
   → adapter 里保留 `aweme["comment_count"]` 兜底读取，UI 上不要对 0 做强解释。

### 单次调用耗时（实测，headed Chrome，本机）

| 动作 | 耗时 |
|---|---|
| 启动 + 首屏第一条 feed | 6~15s |
| 每次滚动追加 | ~4s（settle_ms） |
| 抓一条视频的评论 | 6~12s（轮询到 `>=3` 条就停） |

结论：feed 走**常驻会话 + 10 分钟缓存**，评论走**点开才抓 + 单条缓存**。别在首屏同步等评论。
