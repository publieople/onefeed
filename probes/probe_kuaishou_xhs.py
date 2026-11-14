import json, re, sys, urllib.error, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def gql(op, variables, query):
    body = json.dumps({"operationName": op, "variables": variables, "query": query}).encode()
    req = urllib.request.Request("https://www.kuaishou.com/graphql", data=body, method="POST",
        headers={"User-Agent": UA, "Content-Type": "application/json", "Referer": "https://www.kuaishou.com/"})
    return json.loads(OPENER.open(req, timeout=15).read())

print("=== 快手 graphql 候选 query ===")
for op, variables, query in [
    ("brilliantTypeData", {"pcursor": "", "page": "brilliant", "type": 0},
     "query brilliantTypeData($pcursor: String, $page: String, $type: Int) { brilliantTypeData(pcursor: $pcursor, page: $page, type: $type) { feeds { photo { id caption } } pcursor } }"),
    ("visionHotRank", {"page": "home"},
     "query visionHotRank($page: String) { visionHotRank(page: $page) { result items { id name } } }"),
]:
    try:
        resp = gql(op, variables, query)
        print(f"  {op}: keys={list((resp.get('data') or {}).keys())} errors={str(resp.get('errors'))[:120]}")
        node = (resp.get("data") or {}).get(op) or {}
        print(f"     node keys={list(node)[:6]} sample={json.dumps(node, ensure_ascii=False)[:160]}")
    except urllib.error.HTTPError as e:
        print(f"  {op}: HTTP {e.code} {e.read(200).decode('utf-8','replace')[:120]}")

print("\n=== 小红书 /explore SSR 结构 ===")
st, html = get = None, None
resp = OPENER.open(urllib.request.Request("https://www.xiaohongshu.com/explore", headers={"User-Agent": UA}), timeout=20)
html = resp.read(600_000).decode("utf-8", "replace")
m = re.search(r"window\.__INITIAL_STATE__=(\{.*?\})</script>", html, re.S)
data = json.loads(m.group(1))
print("  top keys:", list(data)[:8])
feed = (data.get("feed") or {})
print("  feed keys:", list(feed)[:8])
for k in ("feeds", "items", "_rawValue"):
    v = feed.get(k)
    if isinstance(v, list):
        print(f"  feed.{k}: {len(v)} 条; 首条 keys: {list(v[0])[:12] if isinstance(v[0], dict) else type(v[0])}")
    elif v is not None:
        print(f"  feed.{k}: {type(v).__name__} {str(v)[:80]}")
