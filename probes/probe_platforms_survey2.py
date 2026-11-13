"""第二轮普查：换上更可能的端点 + 检查 HTML 里的内嵌 JSON。"""
from __future__ import annotations
import json, re, sys, urllib.error, urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

TARGETS = [
    ("C", "知乎 hot-list-web", "GET", "https://www.zhihu.com/api/v3/feed/topstory/hot-list-web?limit=20&desktop=true", None, {}),
    ("C", "头条热榜", "GET", "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc", None, {}),
    ("C", "微博 关注流 header", "GET", "https://m.weibo.cn/api/container/getIndex?containerid=102803&openApp=0",
     None, {"Referer": "https://m.weibo.cn/", "X-Requested-With": "XMLHttpRequest"}),
    ("B", "B站热门", "GET", "https://api.bilibili.com/x/web-interface/popular?ps=10&pn=1", None, {}),
    ("B", "CSDN 首页推荐", "GET", "https://blog.csdn.net/api/articles?type=more&category=home&shown_offset=0", None, {}),
    ("B", "InfoQ 文章列表", "POST", "https://www.infoq.cn/public/v1/article/list",
     json.dumps({"page": 1, "size": 10}).encode(), {"Content-Type": "application/json"}),
    ("B", "什么值得买", "GET", "https://post.smzdm.com/feed/", None, {}),
    ("B", "36氪 热榜 API", "POST", "https://gateway.36kr.com/api/mis/nav/home/nav/rank/hot",
     json.dumps({"partner_id": "wap", "param": {"siteId": 1, "platformId": 2}}).encode(),
     {"Content-Type": "application/json"}),
    ("B", "虎扑步行街", "GET", "https://bbs.hupu.com/all-gambia", None, {}),
    ("A", "mastodon.online 公共线", "GET", "https://mastodon.online/api/v1/timelines/public?limit=5", None, {}),
    ("A", "Mastodon 应用注册", "POST", "https://mastodon.online/api/v1/apps",
     b"client_name=onefeed&redirect_uris=urn:ietf:wg:oauth:2.0:oob&scopes=read", {"Content-Type": "application/x-www-form-urlencoded"}),
    ("A", "Reddit old + 自定义 UA", "GET", "https://old.reddit.com/r/programming/hot.json?limit=5", None, {"User-Agent": "onefeed/0.1 (by /u/publieople)"}),
    ("A", "YouTube Data API", "GET", "https://www.googleapis.com/youtube/v3/videos?part=snippet&chart=mostPopular&maxResults=5&regionCode=CN", None, {}),
    ("D", "抖音热榜(免签)", "GET", "https://www.douyin.com/aweme/v1/web/hot/search/list/?device_platform=webapp&aid=6383", None, {}),
    ("D", "快手 graphql 热榜", "POST", "https://www.kuaishou.com/graphql",
     json.dumps({"operationName": "visionHotRank", "variables": {"page": "home"}, "query": "query visionHotRank($page: String) { visionHotRank(page: $page) { result items { id name hotValue } } }"}).encode(),
     {"Content-Type": "application/json", "Referer": "https://www.kuaishou.com/"}),
]

PROXIES = [None, "http://127.0.0.1:7890"]
MARKERS = ["__APOLLO_STATE__", "window.__INITIAL_STATE__", "RENDER_DATA", "window.__NUXT__", "SSR_RENDER_DATA"]

def fetch(method, url, body, headers, proxy):
    h = {"User-Agent": UA, "Accept": "application/json,text/html,*/*", "Accept-Language": "zh-CN,zh;q=0.9"}
    h.update(headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({} if proxy is None else {"http": proxy, "https": proxy}))
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    with opener.open(req, timeout=15) as resp:
        return resp.status, resp.headers.get("Content-Type", ""), resp.read(600_000)

out = []
for group, name, method, url, body, headers in TARGETS:
    for proxy in PROXIES:
        try:
            status, ctype, raw = fetch(method, url, body, headers, proxy)
            text = raw.decode("utf-8", "replace")
            kind = "JSON" if text.strip()[:1] in "[{" else (ctype or "text")[:22]
            found = [m for m in MARKERS if m in text]
            preview = text.strip()[:130].replace("\n", " ")
            out.append({"group": group, "name": name, "status": status, "bytes": len(raw), "kind": kind, "markers": found, "preview": preview})
            print(f"[{group}] {name:20} {status} {len(raw):>7}B {kind:22} markers={found} via {proxy or 'direct'}")
            print(f"      {preview[:110]}")
            break
        except urllib.error.HTTPError as exc:
            detail = ""
            try: detail = exc.read(150).decode("utf-8", "replace").replace("\n", " ")
            except Exception: pass
            out.append({"group": group, "name": name, "status": exc.code, "bytes": 0, "kind": "HTTPError", "markers": [], "preview": detail})
            print(f"[{group}] {name:20} {exc.code} HTTPError :: {detail[:90]}")
            break
        except Exception as exc:
            if proxy == PROXIES[-1]:
                out.append({"group": group, "name": name, "status": 0, "bytes": 0, "kind": "FAIL", "markers": [], "preview": f"{type(exc).__name__}: {exc}"})
                print(f"[{group}] {name:20} FAIL {type(exc).__name__}: {str(exc)[:70]}")

json.dump(out, open("probes/tmp_survey2.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"\n{len(out)} -> probes/tmp_survey2.json")
