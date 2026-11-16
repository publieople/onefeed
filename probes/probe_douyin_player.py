
import json, sys, urllib.request
from pathlib import Path
sys.path.insert(0, str(Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed")))
from plugin_runtime.manifest import load_manifest
from plugin_runtime.capabilities import Capabilities

PLUG = Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed-plugins/plugins")
m = load_manifest(PLUG / "douyin")
cap = Capabilities(m, settings={})
r = json.loads(cap.handle(json.dumps({"cap": "browser",
    "url": "https://www.douyin.com/video/7677413413173169449",
    "patterns": [r"aweme/detail"], "settleMs": 5000, "timeoutMs": 60000,
    "scroll": {"times": 0}}, ensure_ascii=False)))
found = None
for resp in (r.get("data", {}).get("responses") or []):
    j = resp.get("json")
    if isinstance(j, dict) and j.get("aweme_detail"):
        found = j["aweme_detail"]; break
if not found:
    print("no detail"); raise SystemExit
v = found.get("video") or {}
pa = v.get("play_addr") or {}
uri = pa.get("uri") or ""
print("play_addr.uri:", uri[:80])
print("video_id:", found.get("aweme_id"), "vid?", (v.get("vid") or "")[:40])

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
def head(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as resp:
            hs = {k.lower(): v for k, v in resp.headers.items()}
            return resp.status, hs.get("content-type"), hs.get("x-frame-options"), (hs.get("content-security-policy") or "")[:90], len(resp.read(512))
    except Exception as e:
        return getattr(e, "code", 0), None, None, str(e)[:80], 0

cands = [
    f"https://open.douyin.com/player/video?vid={uri}&autoplay=0",
    f"https://www.douyin.com/player/video?vid={uri}&autoplay=0",
    f"https://open.douyin.com/player/video?vid={found.get('aweme_id')}",
]
for u in cands:
    st, ct, xfo, csp, n = head(u)
    print(f"{u[:88]}\n   status={st} ct={ct} XFO={xfo} CSP={csp} bytes={n}")
