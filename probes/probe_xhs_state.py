
import json, re, sys
from pathlib import Path
sys.path.insert(0, str(Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed")))
from plugin_runtime.manifest import load_manifest
from plugin_runtime.capabilities import Capabilities

PLUG = Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed-plugins/plugins")
NOTE = ("https://www.xiaohongshu.com/explore/6aeac597000000000e0340ac"
        "?xsec_token=ABvnRvD6UTv9uAI53rO38JreTlBG5X4Bu08atTCszOdCI%3D&xsec_source=pc_feed")
m = load_manifest(PLUG / "xiaohongshu")
cap = Capabilities(m, settings={})
raw = cap.handle(json.dumps({"cap": "browser", "url": NOTE,
    "patterns": [r"api/sns/web/v1/note/metrics_report"], "html": True,
    "settleMs": 6000, "timeoutMs": 60000, "scroll": {"times": 0}}, ensure_ascii=False))
d = json.loads(raw)["data"]
html = d.get("html") or ""
Path("probes/tmp_xhs_note.html").write_text(html, encoding="utf-8")
i = html.find("window.__INITIAL_STATE__")
j = html.find("=", i) + 1
state, end = json.JSONDecoder().raw_decode(html[j:].lstrip())
print("decoded ok, top keys:", list(state.keys())[:14])
ndm = (state.get("note") or {}).get("noteDetailMap") or {}
print("noteDetailMap:", len(ndm))
note = {}
for k, v in ndm.items():
    note = (v or {}).get("note") or {}
    if note: print("key:", k[:40], "note keys:", len(note.keys())); break
if note:
    print("title:", (note.get("title") or "")[:60])
    print("desc:", (note.get("desc") or "")[:150].replace("\n", " "))
    print("type:", note.get("type"))
    imgs = note.get("imageList") or []
    print("images:", len(imgs))
    if imgs:
        print("img0 keys:", list(imgs[0].keys())[:12])
        print("img0 url:", (imgs[0].get("urlDefault") or imgs[0].get("url") or "")[:100])
    vid = note.get("video") or {}
    if vid:
        st = ((vid.get("media") or {}).get("stream") or {})
        print("video stream codecs:", list(st.keys()))
        for codec in ("h264", "h265", "av1"):
            arr = st.get(codec) or []
            if arr:
                print(f"  {codec}[0] master:", (arr[0].get("masterUrl") or arr[0].get("master_url") or "")[:100])
                print(f"  {codec}[0] backup:", len(arr[0].get("backupUrls") or arr[0].get("backup_urls") or []))
                break
    print("user:", ((note.get("user") or {}).get("nickname")), "id:", ((note.get("user") or {}).get("userId")))
    print("interact:", {kk: (note.get("interactInfo") or {}).get(kk) for kk in ("likedCount","commentCount","collectedCount")})
    print("time:", note.get("time"), "ip:", note.get("ipLocation"))
print()
print("== xhs comments path? ==")
for k in state.keys():
    print(" state key:", k, type(state[k]).__name__)
