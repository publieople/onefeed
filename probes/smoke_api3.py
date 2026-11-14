import sys, json, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from fastapi.testclient import TestClient
from onefeed.app import create_app
from onefeed import smart

c = TestClient(create_app())
print("health", c.get("/api/health").json())
f = c.get("/api/feed", params={"limit": 4}).json()
print("feed", f["count"])
for it in f["items"]:
    print(" -", it["platform"], it["kind"], (it["title"] or "")[:26], "| reasons:", it.get("reasons"), "| cluster:", it.get("cluster_size"))
print("q-parse", c.get("/api/feed", params={"q": "只看今天 B 站的 AI", "limit": 2}).json().get("parsed"))
print("summary", c.get("/api/summary").json())
print("auth", c.get("/api/auth/xiaohongshu").json())
t0 = time.time()
pl = c.get("/api/plugins").json()
print("plugins market", round(time.time()-t0,1), "s entries", len(pl["market"]["entries"]), "degraded", pl["market"]["degraded"][:80])
print("first", json.dumps(pl["market"]["entries"][0], ensure_ascii=False)[:300] if pl["market"]["entries"] else None)
