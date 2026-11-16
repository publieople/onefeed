
import json, sys, urllib.request, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed")))
from plugin_runtime.manifest import load_manifest
from plugin_runtime.capabilities import Capabilities

PLUG = Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed-plugins/plugins")
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"

def capture(plugin, url, patterns, scroll_times=1, settle=5000):
    m = load_manifest(PLUG / plugin)
    cap = Capabilities(m, settings={})
    raw = cap.handle(json.dumps({"cap": "browser", "url": url, "patterns": patterns,
        "settleMs": settle, "timeoutMs": 60000,
        "scroll": {"times": scroll_times, "dy": 1200, "intervalMs": 900}}, ensure_ascii=False))
    return json.loads(raw)

def probe(url, referer=None):
    h = {"User-Agent": UA, "Range": "bytes=0-2047"}
    if referer: h["Referer"] = referer
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25) as r:
            return r.status, r.headers.get("Content-Type"), r.headers.get("Content-Length"), len(r.read())
    except Exception as e:
        return getattr(e, "code", 0), None, None, str(e)[:120]

print("== DOUYIN direct url ==")
d = capture("douyin", "https://www.douyin.com/video/7677413413173169449", [r"aweme/detail"])
found = None
for resp in (d.get("data", {}).get("responses") or []):
    j = resp.get("json")
    if isinstance(j, dict) and j.get("aweme_detail"):
        found = j["aweme_detail"]; break
if found:
    v = found.get("video") or {}
    urls = (v.get("play_addr") or {}).get("url_list") or []
    for i, u in enumerate(urls[:2]):
        host = urllib.parse.urlparse(u).hostname
        print(f" url[{i}] host={host} params={len(urllib.parse.parse_qs(urllib.parse.urlparse(u).query))}")
    if urls:
        for label, ref in (("no-referer", None), ("referer=douyin.com", "https://www.douyin.com/"),
                           ("referer=www.douyin.com/video", "https://www.douyin.com/video/7677413413173169449")):
            print(f"  {label}:", probe(urls[0], ref))

print()
print("== XHS note detail ==")
NOTE = ("https://www.xiaohongshu.com/explore/6aeac597000000000e0340ac"
        "?xsec_token=ABvnRvD6UTv9uAI53rO38JreTlBG5X4Bu08atTCszOdCI%3D&xsec_source=pc_feed")
x = capture("xiaohongshu", NOTE, [r"api/sns/web/v1/(feed|note)"], scroll_times=0, settle=6000)
if not x.get("ok"):
    print("ERR", x.get("error"))
else:
    dx = x["data"]
    print("final url:", dx.get("url")[:100])
    print("responses:", len(dx.get("responses") or []))
    for resp in (dx.get("responses") or [])[:2]:
        print("  hit:", resp.get("url", "")[:100])
    card = None
    for resp in (dx.get("responses") or []):
        j = resp.get("json") or {}
        items = j.get("data", {}).get("items") if isinstance(j.get("data"), dict) else None
        if items:
            card = items[0].get("note_card") or items[0]; break
    if card:
        print("title:", (card.get("title") or "")[:50])
        print("desc:", (card.get("desc") or "")[:100].replace("\n", " "))
        print("images:", len(card.get("image_list") or []))
        vid = card.get("video")
        if vid:
            h264 = (((vid.get("media") or {}).get("stream") or {}).get("h264") or [])
            print("video h264:", len(h264), (h264[0].get("master_url") or "")[:90] if h264 else "")
        print("interact:", {k: (card.get("interact_info") or {}).get(k) for k in ("liked_count","comment_count","collected_count")})
        print("user:", ((card.get("user") or {}).get("nickname")))
    else:
        print("no note_card captured")
