import sys, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from onefeed.store import Store
from onefeed.service import RefreshRunner

store = Store()
runner = RefreshRunner(store, limit=12)
started, state = runner.trigger(warmup=True)
print("started", started, "total", state["total"], flush=True)
while runner.running():
    time.sleep(2)
    st = runner.snapshot()
    print("done", st["done"], "/", st["total"], flush=True)
print("fixtures:", sorted(p.name for p in __import__("pathlib").Path("fixtures").glob("*.json")))
store.close_all()
