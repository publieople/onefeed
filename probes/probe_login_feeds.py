"""第三轮：专门看「登录态 + 个性化流」这条路——哪些平台只差 cookie，哪些还差签名。

判据：
  200 + 真数据  → 无需签名、可能连 cookie 都不用/或 cookie 就够了
  401/403      → 需要登录（还需判断是否叠加签名）
  432          → 微博系风控（要 cookie + 设备指纹）
  406/461      → 明确要求签名头
"""
from __future__ import annotations
import json, sys, urllib.error, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

TARGETS = [
    # 国内主流社交：个性化推荐流 / 关注流
    ("微博 推荐流", "GET", "https://m.weibo.cn/api/container/getIndex?containerid=102803&openApp=0", None,
     {"Referer": "https://m.weibo.cn/", "X-Requested-With": "XMLHttpRequest", "MWeibo-Pwa": "1"}),
    ("微博 关注流", "GET", "https://m.weibo.cn/api/container/getIndex?containerid=231093_-_selffollowed", None,
     {"Referer": "https://m.weibo.cn/"}),
    ("微博 web 推荐", "GET", "https://weibo.com/ajax/feed/hottimeline?since_id=0&refresh=0&group_id=102803&containerid=102803&extparam=discover&max_id=0&count=10", None, {}),
    ("知乎 推荐流", "GET", "https://www.zhihu.com/api/v3/feed/topstory/recommend?desktop=true&page_number=1&limit=6", None, {}),
    ("知乎 关注流", "GET", "https://www.zhihu.com/api/v3/moments?limit=10&desktop=true", None, {}),
    ("B站 关注动态", "GET", "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all?timezone_offset=-480&type=all&page=1", None, {}),
    ("快手 首页推荐", "GET", "https://www.kuaishou.com/?isHome=1", None, {}),
    ("贴吧 关注流", "GET", "https://tieba.baidu.com/f?kw=%E7%A8%8B%E5%BA%8F%E5%91%98&ie=utf-8", None, {}),
    ("豆瓣 广播", "GET", "https://www.douban.com/j/feed/recommend", None, {}),
    ("即刻 推荐流", "GET", "https://web-api.okjike.com/api/general/feed", None, {"Referer": "https://web.okjike.com/"}),
    ("网易云 关注动态", "GET", "https://music.163.com/api/event/get?limit=10&offset=0", None, {"Referer": "https://music.163.com/"}),
    ("虎扑 推荐", "GET", "https://bbs.hupu.com/all-gambia", None, {}),
    ("小红书 探索页", "GET", "https://www.xiaohongshu.com/explore", None, {}),
    ("B站 首页推荐(无登录)", "GET", "https://api.bilibili.com/x/web-interface/wbi/index/top/feed/rcmd?ps=6&fresh_type=3", None, {}),
    ("掘金 关注流", "GET", "https://api.juejin.cn/recommend_api/v1/article/recommend_cate_feed", None, {"Content-Type": "application/json"}),
]

PROXIES = [None, "http://127.0.0.1:7890"]

def fetch(method, url, body, headers, proxy):
    h = {"User-Agent": UA, "Accept": "application/json,text/html,*/*", "Accept-Language": "zh-CN,zh;q=0.9"}
    h.update(headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({} if proxy is None else {"http": proxy, "https": proxy}))
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    with opener.open(req, timeout=15) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read(200_000)

for name, method, url, body, headers in TARGETS:
    line = f"{name:16} "
    for proxy in PROXIES:
        try:
            status, ctype, raw = fetch(method, url, body, headers, proxy)
            text = raw.decode("utf-8", "replace").strip()
            looks_json = text[:1] in "[{"
            note = ""
            if looks_json:
                try:
                    data = json.loads(text)
                    if isinstance(data, list):
                        note = f"list[{len(data)}]"
                    elif isinstance(data, dict):
                        note = "keys=" + str(list(data)[:5])
                except Exception:
                    pass
            line += f"| {status} {len(raw)}B {'JSON' if looks_json else (ctype or '')[:18]} {note[:55]} "
            break
        except urllib.error.HTTPError as exc:
            detail = ""
            try: detail = exc.read(120).decode("utf-8", "replace").replace("\n", " ")
            except Exception: pass
            line += f"| {exc.code} {detail[:60]} "
            break
        except Exception as exc:
            if proxy == PROXIES[-1]:
                line += f"| FAIL {type(exc).__name__} "
    print(line)
