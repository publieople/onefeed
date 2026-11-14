import json, re, sys, urllib.error, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

def get(url, headers=None, proxy=None, raw=False):
    h = {"User-Agent": UA, "Accept": "application/json,text/html,*/*", "Accept-Language": "zh-CN,zh;q=0.9"}
    h.update(headers or {})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({} if proxy is None else {"http": proxy, "https": proxy}))
    resp = opener.open(urllib.request.Request(url, headers=h), timeout=15)
    data = resp.read(400_000)
    if raw:
        return resp.status, data
    try:
        return resp.status, json.loads(data)
    except Exception:
        return resp.status, data.decode("utf-8", "replace")

print("=== 小响应体，看是不是「只差 cookie」 ===")
for name, url, hdr in [
    ("微博推荐", "https://m.weibo.cn/api/container/getIndex?containerid=102803&openApp=0", {"Referer": "https://m.weibo.cn/"}),
    ("B站动态", "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all?type=all&page=1", {}),
    ("网易云动态", "https://music.163.com/api/event/get?limit=10", {"Referer": "https://music.163.com/"}),
    ("掘金关注流", "https://api.juejin.cn/recommend_api/v1/article/recommend_cate_feed", {"Referer": "https://juejin.cn/"}),
]:
    try:
        st, body = get(url, hdr)
        print(f"{name:10} {st} {json.dumps(body, ensure_ascii=False)[:220] if isinstance(body, (dict, list)) else str(body)[:220]}")
    except urllib.error.HTTPError as e:
        print(f"{name:10} {e.code} {e.read(200).decode('utf-8','replace')[:200]}")

print("\n=== 小红书 /explore 首屏 SSR 里有没有笔记数据 ===")
st, html = get("https://www.xiaohongshu.com/explore", {"Accept": "text/html"}, raw=True)
html = html.decode("utf-8", "replace")
for marker in ["__INITIAL_STATE__", "noteCard", "window.__NUXT__"]:
    print(f"  {marker}: {'有' if marker in html else '无'}  count={html.count(marker)}")
m = re.search(r"window\.__INITIAL_STATE__=(\{.*?\})</script>", html, re.S)
print("  SSR JSON 可解析:", bool(m), "长度:", len(m.group(1)) if m else 0)

print("\n=== 快手 graphql：不用签名能不能直接拿首页 feed ===")
body = json.dumps({
    "operationName": "brilliantTypeDataQuery",
    "variables": {"pcursor": "", "page": "brilliant", "type": 0},
    "query": "query brilliantTypeDataQuery($pcursor: String, $page: String, $type: Int) { brilliantTypeDataQuery(pcursor: $pcursor, page: $page, type: $type) { feeds { photo { id caption } } pcursor } }",
}).encode()
req = urllib.request.Request("https://www.kuaishou.com/graphql", data=body, method="POST",
                             headers={"User-Agent": UA, "Content-Type": "application/json", "Referer": "https://www.kuaishou.com/"})
try:
    resp = json.loads(urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=15).read())
    feeds = (((resp.get("data") or {}).get("brilliantTypeDataQuery") or {}).get("feeds") or [])
    print("  status=data, feeds:", len(feeds), "| pcursor:", ((resp.get("data") or {}).get("brilliantTypeDataQuery") or {}).get("pcursor"))
    print("  sample:", json.dumps(feeds[:1], ensure_ascii=False)[:200])
except urllib.error.HTTPError as e:
    print("  HTTPError", e.code, e.read(200).decode("utf-8", "replace")[:150])
