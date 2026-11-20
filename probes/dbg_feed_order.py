import sys, time, json
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from fastapi.testclient import TestClient
from onefeed.app import create_app
from onefeed.store import Store, SORTS, FRESH_KEY
tmp = Path(".onefeed/tmp"); db = tmp/"api-test-dbg.db"
for f in (db, Path(str(db)+"-wal"), Path(str(db)+"-shm")): f.unlink(missing_ok=True)
s = Store(db)
now = int(time.time())
rows = [{"id": f"{'bilibili' if i%2==0 else 'xiaohongshu'}:{i}", "platform": "bilibili" if i%2==0 else "xiaohongshu",
         "kind": "video" if i%2==0 else "images", "title": f"标题 {i}", "text":"", "author": f"作者{i}",
         "cover": f"https://e.com/{i}.jpg", "url": f"https://e.com/p/{i}", "published_at": now-i*3600,
         "like": 10*i, "comment": i, "share": 0, "view": 100*i, "tags": [], "extra": {}, "fetched_at": now} for i in range(6)]
s.upsert_items(rows)
c = TestClient(create_app(s))
j = c.get("/api/feed").json()
print("SORTS:", SORTS["freshness"], "| FRESH_KEY:", FRESH_KEY)
print("count:", j["count"])
for it in j["items"]:
    print(it["id"], it.get("published_at"), it.get("fetched_at"))
