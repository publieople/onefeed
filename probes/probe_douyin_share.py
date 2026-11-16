
import json, re, urllib.request

VID = "7677413413173169449"
UA_M = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
req = urllib.request.Request(f"https://www.iesdouyin.com/share/video/{VID}/",
                            headers={"User-Agent": UA_M, "Accept-Language": "zh-CN,zh;q=0.9"})
with urllib.request.urlopen(req, timeout=25) as r:
    txt = r.read().decode("utf-8", "replace")
data = json.loads(re.search(r"window\._ROUTER_DATA\s*=\s*(\{.*?\});?\s*</script>", txt, re.S).group(1))
loader = data.get("loaderData", {})
for k, v in loader.items():
    print("KEY", k, "type", type(v).__name__)
    if isinstance(v, dict):
        print("   subkeys:", list(v.keys())[:12])
print("---- raw markers ----")
for marker in ("play_addr", "url_list", "videoInfoRes", "playApi", "aweme_id", "video_id"):
    print(marker, "count", txt.count(marker))
idx = txt.find("playApi")
print("playApi ctx:", txt[max(0, idx-200):idx+300].replace("\n", " ") if idx > 0 else "none")
