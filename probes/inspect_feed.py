
import json
p = r"E:\Documents\deepseek-harness\default-workspace\onefeed\tmp_feed_resp.json"
rec = json.load(open(p, encoding="utf-8"))
items = rec["body"]["aweme_list"]
print("N", len(items))
for it in items[:4]:
    v = it.get("video") or {}
    cov = (v.get("cover") or {}).get("url_list") or (v.get("origin_cover") or {}).get("url_list") or []
    st = it.get("statistics") or {}
    print(json.dumps({
        "aweme_id": it.get("aweme_id"),
        "desc": (it.get("desc") or "")[:50],
        "author": (it.get("author") or {}).get("nickname"),
        "author_sec_uid": ((it.get("author") or {}).get("sec_uid") or "")[:20],
        "create_time": it.get("create_time"),
        "duration_ms": v.get("duration"),
        "cover": cov[0][:100] if cov else None,
        "digg": st.get("digg_count"), "comment": st.get("comment_count"),
        "share": st.get("share_count"), "play": st.get("play_count"),
        "share_url": ((it.get("share_info") or {}).get("share_url") or "")[:80],
    }, ensure_ascii=False))
print("--- has fields:", [k for k in ("aweme_id","desc","author","create_time","statistics","video","share_info") if k in items[0]])
