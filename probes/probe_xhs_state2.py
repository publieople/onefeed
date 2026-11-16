
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed")))
html = Path("probes/tmp_xhs_note.html").read_text(encoding="utf-8")
i = html.find("window.__INITIAL_STATE__")
j = html.find("=", i) + 1
s = html[j:].lstrip()
print("snippet around 2947:", repr(s[2920:2990]))
s = re.sub(r"(?<=[:,\[])\s*undefined\s*(?=[,\]}])", "null", s)
s = re.sub(r"(?<=[:,\[])\s*NaN\s*(?=[,\]}])", "null", s)
try:
    state, end = json.JSONDecoder().raw_decode(s)
except json.JSONDecodeError as e:
    print("still bad at", e.pos, repr(s[max(0,e.pos-80):e.pos+80]))
    raise SystemExit
print("decoded ok, top keys:", list(state.keys())[:14])
ndm = (state.get("note") or {}).get("noteDetailMap") or {}
print("noteDetailMap:", len(ndm))
note = {}
for k, v in ndm.items():
    note = (v or {}).get("note") or {}
    if note:
        print("key:", k[:40]); break
if note:
    print("title:", (note.get("title") or "")[:60])
    print("desc:", (note.get("desc") or "")[:150].replace("\n", " "))
    print("type:", note.get("type"))
    imgs = note.get("imageList") or []
    print("images:", len(imgs))
    if imgs:
        print("img0 keys:", list(imgs[0].keys())[:12])
    vid = note.get("video") or {}
    if vid:
        st = ((vid.get("media") or {}).get("stream") or {})
        print("stream codecs:", list(st.keys()))
        for codec in ("h264", "h265", "av1"):
            arr = st.get(codec) or []
            if arr:
                url = arr[0].get("masterUrl") or arr[0].get("master_url") or ""
                print(f"  {codec}[0]:", url[:110])
                print(f"  {codec}[0] backups:", len(arr[0].get("backupUrls") or arr[0].get("backup_urls") or []))
                break
    print("user:", ((note.get("user") or {}).get("nickname")))
    print("interact:", {kk: (note.get("interactInfo") or {}).get(kk) for kk in ("likedCount","commentCount","collectedCount")})
print("state keys:", list(state.keys()))
