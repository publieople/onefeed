import sys, time
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass
from pathlib import Path
ROOT = Path(r"E:\\Documents\\deepseek-harness\\default-workspace\\onefeed")
sys.path.insert(0, str(ROOT))
from onefeed.store import Store
from onefeed import ai as ai_mod

db = ROOT / ".onefeed" / "onefeed.db"
store = Store(db)
print("库内", store.count(), "条")
t0 = time.time()
out = ai_mod.chat(store, "找几条 B 站讲 AI 的视频，十分钟以内", limit=6)
print("engine:", out["engine"], "steps:", out.get("steps"), "ms:", out.get("ms"), "tokens:", out.get("tokens"))
print("plan:", out["plan"])
print("reply:", out["reply"])
print("count:", out["count"], "understood:", out["understood"])
for it in out["items"]:
    print(" -", it["platform"], "|", it["title"][:40], "|", round((it.get("duration") or 0)/60,1), "min")
print("wall", round(time.time()-t0, 2), "s")
print("last:", ai_mod.status().get("last"))
