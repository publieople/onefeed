import json, sys, traceback
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from plugin_runtime.host import PluginHost
from onefeed.store import Store

host = PluginHost()
row = Store().get_item("bilibili:video:BV1ZMWd6mE77")
try:
    src = host.summary_source("bilibili", row)
    print("TYPE:", type(src).__name__)
    if isinstance(src, dict):
        print("basis=", src.get("basis"), "duration=", src.get("duration"))
        tr = src.get("transcript") or {}
        lines = tr.get("lines") or []
        print("lines=", len(lines), "first=", json.dumps(lines[:2], ensure_ascii=False))
except Exception:
    traceback.print_exc()
