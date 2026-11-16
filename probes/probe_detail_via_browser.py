
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed")))
from plugin_runtime.manifest import load_manifest
from plugin_runtime.capabilities import Capabilities

PLUG = Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed-plugins/plugins")

def run(plugin, url, patterns, scroll_times=2):
    m = load_manifest(PLUG / plugin)
    cap = Capabilities(m, settings={})
    raw = cap.handle(json.dumps({
        "cap": "browser", "url": url, "patterns": patterns,
        "settleMs": 5000, "timeoutMs": 60000,
        "scroll": {"times": scroll_times, "dy": 1400, "intervalMs": 900},
    }, ensure_ascii=False))
    return json.loads(raw)

print("== DOUYIN detail ==")
r = run("douyin", "https://www.douyin.com/video/7677413413173169449",
        [r"aweme/detail", r"aweme_detail", r"/aweme/v1/web/"])
if not r.get("ok"):
    print("ERR", r.get("error"))
else:
    d = r["data"]
    print("final url:", d.get("url"))
    print("responses:", len(d.get("responses") or []))
    for resp in (d.get("responses") or [])[:3]:
        print("  hit:", resp.get("url","")[:110])
    found = None
    for resp in (d.get("responses") or []):
        j = resp.get("json")
        if isinstance(j, dict) and (j.get("aweme_detail") or j.get("awemeDetail")):
            found = j.get("aweme_detail") or j.get("awemeDetail"); break
    if found:
        print("desc:", (found.get("desc") or "")[:60])
        v = found.get("video") or {}
        pa = (v.get("play_addr") or {}).get("url_list") or []
        print("play urls:", len(pa), (pa[0][:110] if pa else ""))
        print("cover:", (((v.get("cover") or {}).get("url_list") or [""])[0])[:80])
        print("images:", len(found.get("images") or []))
        print("stats:", {k: (found.get("statistics") or {}).get(k) for k in ("digg_count","comment_count","play_count")})
    else:
        print("no aweme_detail in captured bodies")
        if d.get("responses"):
            j0 = d["responses"][0].get("json")
            print("first body keys:", list(j0.keys())[:10] if isinstance(j0, dict) else type(j0).__name__)
