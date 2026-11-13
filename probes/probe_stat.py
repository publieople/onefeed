
import json
from playwright.sync_api import sync_playwright
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
raw = []
def on_resp(r):
    if "/aweme/v2/web/module/feed/" not in r.url: return
    try: b = r.json()
    except Exception: return
    lst = b.get("aweme_list") or []
    if lst: raw.append(lst[0])
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROME, headless=False, args=["--disable-blink-features=AutomationControlled"])
    ctx = br.new_context(locale="zh-CN", viewport={"width":1440,"height":900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
    page = ctx.new_page(); page.on("response", on_resp)
    page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(9000)
    ctx.close(); br.close()
it = raw[0]
print("TOPKEYS", [k for k in it.keys()][:40])
print("STAT", json.dumps(it.get("statistics"), ensure_ascii=False))
print("VIDEO_KEYS", list((it.get("video") or {}).keys())[:20])
