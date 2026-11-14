
import json, urllib.request
cookies = json.load(open(r"E:\Documents\deepseek-harness\default-workspace\onefeed\probes\tmp_xhs_cookies3.json", encoding="utf-8"))["cookies"]
ck = "; ".join(f"{k}={v}" for k, v in cookies.items())
req = urllib.request.Request("https://www.xiaohongshu.com/api/sns/web/v2/user/me", headers={
  "Cookie": ck,
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
  "Referer": "https://www.xiaohongshu.com/",
  "Accept": "application/json",
})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print("HTTP", r.status)
        print(r.read().decode("utf-8")[:800])
except Exception as e:
    print("ERR", type(e).__name__, str(e)[:300])
