
import json
rec = json.load(open(r"E:\Documents\deepseek-harness\default-workspace\onefeed\tmp_feed_resp.json", encoding="utf-8"))
items = rec["body"]["aweme_list"]
print("N", len(items))
for it in items[:3]:
    print("STATKEYS", sorted((it.get("statistics") or {}).keys()))
    print("STAT", json.dumps(it.get("statistics"), ensure_ascii=False)[:300])
