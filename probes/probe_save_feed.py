
import json
from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
saved = []
def on_resp(resp):
    u = resp.url
    if "/aweme/v2/web/module/feed/" not in u: return
    if saved: return
    try:
        body = resp.json()
    except Exception:
        return
    saved.append({"url": u, "body": body})

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=False, args=["--disable-blink-features=AutomationControlled","--window-size=1440,900"])
    ctx = b.new_context(locale="zh-CN", viewport={"width":1440,"height":900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
    page = ctx.new_page(); page.on("response", on_resp)
    page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(9000)
    ctx.close(); b.close()

if not saved:
    print("NO_SAVE"); raise SystemExit
rec = saved[0]
with open(r"E:\Documents\deepseek-harness\default-workspace\onefeed\tmp_feed_resp.json","w",encoding="utf-8") as f:
    json.dump(rec, f, ensure_ascii=False)
print("URL", rec["url"][:400])
body = rec["body"]
print("KEYS", list(body.keys()))
for k in ("preload_awemes","data","aweme_list"):
    v = body.get(k)
    if isinstance(v, list) and v:
        print("LIST", k, len(v), "itemkeys:", list(v[0].keys())[:20] if isinstance(v[0], dict) else type(v[0]))
