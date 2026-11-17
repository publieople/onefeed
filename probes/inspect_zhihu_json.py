# -*- coding: utf-8 -*-
import json, pathlib
p = pathlib.Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed\probes\tmp_zhihu_recommend.json")
bodies = json.loads(p.read_text(encoding="utf-8"))
print("n bodies", len(bodies))
j = bodies[0]["json"]
data = j.get("data") or []
print("n data", len(data), "paging", json.dumps(j.get("paging"), ensure_ascii=False)[:200])
types = {}
for row in data:
    t = (row.get("target") or {}).get("type")
    types[t] = types.get(t, 0) + 1
print("target types", types)

row = data[0]
tgt = row["target"]
print("\n== feed row keys ==", sorted(row.keys()))
print("verb", row.get("verb"), "type", row.get("type"), "id", row.get("id"), "created", row.get("created_time"))
print("attached_info", json.dumps(row.get("attached_info"), ensure_ascii=False)[:300])
print("action_card", json.dumps(row.get("action_card"), ensure_ascii=False)[:300])
print("\n== target (answer) ==")
for k in ("type","id","url","created_time","updated_time","comment_count","favorite_count","thanks_count","visited_count","voteup_count","answer_type","is_labeled"):
    print(" ", k, "=", tgt.get(k))
au = tgt.get("author") or {}
print(" author:", json.dumps({k: au.get(k) for k in ("name","url_token","id","headline","avatar_url","is_org","type")}, ensure_ascii=False)[:500])
q = tgt.get("question") or {}
print(" question:", json.dumps({k: q.get(k) for k in ("id","type","title","url","created")}, ensure_ascii=False)[:400])
print(" excerpt_new:", str(tgt.get("excerpt_new"))[:160])
print(" content len:", len(str(tgt.get("content") or "")))
print(" reaction:", json.dumps(tgt.get("reaction"), ensure_ascii=False)[:300])
print(" thumbnail:", str(tgt.get("thumbnail"))[:200])
print(" thumbnails:", json.dumps(tgt.get("thumbnails"), ensure_ascii=False)[:300])
print("\n== 第二个 target（article）==")
tgt2 = data[1]["target"]
for k in ("type","id","url","title","created","comment_count","favorite_count","voteup_count","image_url","excerpt_new"):
    v = tgt2.get(k)
    print(" ", k, "=", (json.dumps(v, ensure_ascii=False)[:200] if not isinstance(v, str) else v[:200]))
au2 = tgt2.get("author") or {}
print(" author:", json.dumps({k: au2.get(k) for k in ("name","url_token","id","headline","avatar_url")}, ensure_ascii=False)[:400])
col = tgt2.get("column") or {}
print(" column:", json.dumps({k: col.get(k) for k in ("id","title","url")}, ensure_ascii=False)[:300])
print(" thumbnails:", json.dumps(tgt2.get("thumbnails"), ensure_ascii=False)[:300])
