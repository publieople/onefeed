import sys, time, json
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from fastapi.testclient import TestClient
from onefeed.app import create_app

app = create_app()
c = TestClient(app)
print("health0", c.get("/api/health").json())
r = c.post("/api/refresh", json={})
print("refresh", r.status_code, r.json().get("state", {}).get("total"))
for _ in range(60):
    st = c.get("/api/progress").json()["state"]
    if not st["running"]:
        break
    time.sleep(2)
print("progress", json.dumps(st, ensure_ascii=False)[:500])
feed = c.get("/api/feed", params={"limit": 5}).json()
print("feed", feed["count"], feed.get("parsed"))
for it in feed["items"]:
    print(" -", it["platform"], it["kind"], it["title"][:30], it.get("reasons"), it.get("cluster_size"))
print("summary", c.get("/api/summary").json()["text"])
print("auth", c.get("/api/auth/xiaohongshu").json())
print("plugins", json.dumps(c.get("/api/plugins").json()["market"]["entries"][:2], ensure_ascii=False)[:300])
