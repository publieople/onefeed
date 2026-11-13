
import json, sys
from dy_cli.engines.api_client import DouyinAPIClient

c = DouyinAPIClient(cookie="", timeout=25)
try:
    items = c.get_feed(10)
    print("COUNT", len(items))
    if items:
        it = items[0]
        print("KEYS", list(it.keys())[:25])
        print("DESC", it.get("desc", "")[:80])
        v = it.get("video") or {}
        cov = v.get("cover") or {}
        urls = cov.get("url_list") or []
        print("COVER", urls[0][:100] if urls else None)
        print("STAT", it.get("statistics"))
        print("AUTHOR", (it.get("author") or {}).get("nickname"))
except Exception as e:
    print("ERR", type(e).__name__, str(e)[:300])
finally:
    c.close()
