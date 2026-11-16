
import json, re
from pathlib import Path
html = Path("probes/tmp_zhihu_question.html").read_text(encoding="utf-8")
m = re.search(r'<script id="js-initialData"[^>]*>(.*?)</script>', html, re.S)
print("initialData matched:", bool(m))
if m:
    data = json.loads(m.group(1))
    print("top keys:", list(data.keys()))
    st = data.get("initialState") or {}
    print("initialState keys:", list(st.keys())[:12])
    ent = st.get("entities") or {}
    print("entities:", {k: len(v) if hasattr(v, "__len__") else type(v).__name__ for k, v in ent.items()})
    q = (ent.get("questions") or {})
    for k, v in list(q.items())[:1]:
        print("question:", (v.get("title") or "")[:60], "| answers:", v.get("answerCount"), "| detail len:", len(v.get("detail") or ""))
    a = (ent.get("answers") or {})
    for k, v in list(a.items())[:2]:
        print("answer:", k[:12], "| author:", (v.get("author") or {}).get("name"), "| votes:", v.get("voteupCount"),
              "| content len:", len(v.get("content") or ""), "| excerpt:", (v.get("excerpt") or "")[:70])
