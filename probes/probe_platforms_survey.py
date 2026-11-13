"""平台开放度普查：逐个打点，记录状态码/体积/内容类型/是否 JSON。

一条一条试，直连失败再走本地代理，结果落 probes/tmp_survey.json。
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

TARGETS = [
    # (分组, 名称, 方法, URL, body, headers)
    ("A-official", "Bluesky 公开时间线", "GET",
     "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor=bsky.app&limit=5", None, {}),
    ("A-official", "Mastodon 公共时间线", "GET",
     "https://mastodon.social/api/v1/timelines/public?limit=5", None, {}),
    ("A-official", "HN topstories", "GET",
     "https://hacker-news.firebaseio.com/v0/topstories.json", None, {}),
    ("A-official", "Reddit r/programming", "GET",
     "https://www.reddit.com/r/programming/hot.json?limit=5", None, {}),
    ("A-official", "YouTube 频道 RSS", "GET",
     "https://www.youtube.com/feeds/videos.xml?channel_id=UC_x5XG1OV2P6uZZ5FSM9Ttw", None, {}),
    ("A-official", "V2EX API v2 节点", "GET",
     "https://www.v2ex.com/api/v2/nodes/programmer/topics?page=1", None, {}),
    ("A-official", "Telegram 频道", "GET",
     "https://t.me/s/telegram", None, {}),
    ("A-official", "豆瓣电影 RSS", "GET",
     "https://www.douban.com/feed/subject/1292052/reviews", None, {}),
    ("B-public", "掘金推荐流", "POST",
     "https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed",
     json.dumps({"id_type": 2, "client_type": 2608, "sort_type": 200, "cursor": "0", "limit": 5}).encode(),
     {"Content-Type": "application/json"}),
    ("B-public", "B站排行榜", "GET",
     "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all", None, {}),
    ("B-public", "少数派 RSS", "GET", "https://sspai.com/feed", None, {}),
    ("B-public", "IT之家 RSS", "GET", "https://www.ithome.com/rss/", None, {}),
    ("C-cookie", "微博移动端推荐流", "GET",
     "https://m.weibo.cn/api/container/getIndex?containerid=102803&openApp=0", None, {}),
    ("C-cookie", "微博热搜", "GET", "https://weibo.com/ajax/side/hotSearch", None, {}),
    ("C-cookie", "知乎热榜 v3", "GET",
     "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total?limit=10", None, {}),
    ("C-cookie", "雪球热帖", "GET",
     "https://xueqiu.com/statuses/hot/listV2.json?since_id=-1&max_id=-1&size=10", None, {}),
    ("C-cookie", "今日头条 feed", "GET",
     "https://www.toutiao.com/api/pc/list/feed?channel_id=0&max_behot_time=0", None, {}),
    ("C-cookie", "贴吧热榜", "GET",
     "https://tieba.baidu.com/hottopic/browse/topicList", None, {}),
    ("C-cookie", "豆瓣电影新片", "GET",
     "https://movie.douban.com/j/new_search_subjects?sort=U&range=0,10&tags=&start=0", None, {}),
    ("D-hard", "小红书 homefeed", "POST",
     "https://edith.xiaohongshu.com/api/sns/web/v1/homefeed",
     json.dumps({"cursor_score": "", "num": 5, "refresh_type": 1, "note_index": 0}).encode(),
     {"Content-Type": "application/json"}),
    ("D-hard", "快手首页", "GET", "https://www.kuaishou.com/?isHome=1", None, {}),
    ("D-hard", "36氪 RSS", "GET", "https://36kr.com/feed", None, {}),
]

PROXIES = [None, "http://127.0.0.1:7890", "http://127.0.0.1:10809"]


def fetch(method, url, body, headers, proxy):
    h = {"User-Agent": UA, "Accept": "application/json,text/html,*/*", "Accept-Language": "zh-CN,zh;q=0.9"}
    h.update(headers)
    handlers = [urllib.request.ProxyHandler({} if proxy is None else {"http": proxy, "https": proxy})]
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    with opener.open(req, timeout=12) as resp:
        raw = resp.read(400_000)
        return resp.status, resp.headers.get("Content-Type", ""), raw


def summarize(raw: bytes, ctype: str):
    text = raw.decode("utf-8", errors="replace").strip()
    if "json" in ctype or text[:1] in "[{":
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return f"JSON list[{len(data)}]", str(data[:1])[:150]
            keys = list(data)[:6] if isinstance(data, dict) else []
            return f"JSON dict keys={keys}", text[:150]
        except json.JSONDecodeError:
            return "JSON? 解析失败", text[:120]
    return f"{(ctype or 'text')[:28]} {len(raw)}B", text[:120].replace("\n", " ")


results = []
for group, name, method, url, body, headers in TARGETS:
    for proxy in PROXIES:
        try:
            status, ctype, raw = fetch(method, url, body, headers, proxy)
            kind, preview = summarize(raw, ctype)
            results.append({"group": group, "name": name, "url": url, "status": status,
                            "bytes": len(raw), "kind": kind, "preview": preview,
                            "proxy": proxy or "direct"})
            print(f"[{group:10}] {name:22} {status} {len(raw):>7}B  {kind[:40]:40} via {proxy or 'direct'}")
            break
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read(200).decode("utf-8", "replace").replace("\n", " ")
            except Exception:
                pass
            results.append({"group": group, "name": name, "url": url, "status": exc.code,
                            "bytes": 0, "kind": "HTTPError", "preview": detail, "proxy": proxy or "direct"})
            print(f"[{group:10}] {name:22} {exc.code} HTTPError via {proxy or 'direct'} :: {detail[:80]}")
            break
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            if proxy == PROXIES[-1]:
                results.append({"group": group, "name": name, "url": url, "status": 0,
                                "bytes": 0, "kind": "FAIL", "preview": last, "proxy": proxy})
                print(f"[{group:10}] {name:22} --- FAIL  {last[:70]}")

with open("probes/tmp_survey.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"\n{len(results)} targets -> probes/tmp_survey.json")
