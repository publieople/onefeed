import sys; sys.stdout.reconfigure(encoding="utf-8")
from onefeed.store import Store
s = Store()
print("count", s.count(), "platforms", s.platforms())
print("plugins", [p["id"] for p in s.list_plugins()])
