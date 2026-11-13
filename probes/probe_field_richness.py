"""看新发现端点的字段丰富度：够不够拼一张卡片。"""
from __future__ import annotations
import json, sys, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def get(url, headers=None):
    h = {"User-Agent": UA}
    h.update(headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return json.loads(opener.open(urllib.request.Request(url, headers=h), timeout=15).read())

def post(url, body, headers=None):
    h = {"User-Agent": UA, "Content-Type": "application/json"}
    h.update(headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=h, method="POST")
    return json.loads(opener.open(req, timeout=15).read())

zh = get("https://www.zhihu.com/api/v3/feed/topstory/hot-list-web?limit=20&desktop=true")["data"]
print("== 知乎热榜 ==", len(zh), "条")
for it in zh[:3]:
    t = it.get("target", {})
    print("  keys:", sorted(k for k in t)[:14])
    print("  title:", t.get("title") or t.get("title_area", {}).get("text"))
    print("  metrics:", json.dumps(t.get("metrics_area", {}), ensure_ascii=False)[:160])
    print("  image:", (t.get("image_area", {}) or {}).get("url", "")[:80])

tt = get("https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc")["data"]
print("\n== 头条热榜 ==", len(tt), "条")
print("  keys:", sorted(tt[0]))
print("  sample:", json.dumps({k: tt[0][k] for k in ("Title", "HotValue", "Url") if k in tt[0]}, ensure_ascii=False)[:200])

kr = post("https://gateway.36kr.com/api/mis/nav/home/nav/rank/hot",
          {"partner_id": "wap", "param": {"siteId": 1, "platformId": 2}})["data"]["hotRankList"]
print("\n== 36氪热榜 ==", len(kr), "条")
m = kr[0]["templateMaterial"]
print("  keys:", sorted(m)[:16])
print("  title:", m.get("widgetTitle"), "| author:", m.get("authorName"), "| 阅读:", m.get("statRead"), "| 图:", str(m.get("widgetImage"))[:70])

# B 站热门字段
bp = get("https://api.bilibili.com/x/web-interface/popular?ps=5&pn=1")["data"]["list"]
print("\n== B站热门 ==", len(bp), "条  keys:", sorted(bp[0])[:12])
print("  sample:", bp[0]["title"], bp[0]["owner"]["name"], bp[0]["stat"]["view"], bp[0]["pic"][:50])

# 快手热榜字段
ks = post("https://www.kuaishou.com/graphql",
          {"operationName": "visionHotRank", "variables": {"page": "home"},
           "query": "query visionHotRank($page: String) { visionHotRank(page: $page) { result items { id name hotValue } } }"},
          {"Referer": "https://www.kuaishou.com/"})["data"]["visionHotRank"]["items"]
print("\n== 快手热榜 ==", len(ks), "条  keys:", sorted(ks[0]), "| 样本:", json.dumps(ks[0], ensure_ascii=False)[:120])
