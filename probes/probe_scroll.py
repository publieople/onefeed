
import json
from playwright.sync_api import sync_playwright
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
ids, pages = [], []
def on_resp(resp):
    if "/aweme/v2/web/module/feed/" not in resp.url: return
    try: body = resp.json()
    except Exception: return
    lst = body.get("aweme_list") or []
    pages.append(len(lst))
    for it in lst:
        if it.get("aweme_id"): ids.append(it["aweme_id"])

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=False, args=["--disable-blink-features=AutomationControlled","--window-size=1440,900"])
    ctx = b.new_context(locale="zh-CN", viewport={"width":1440,"height":900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
    page = ctx.new_page(); page.on("response", on_resp)
    page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(8000)
    for i in range(3):
        page.mouse.wheel(0, 3000); page.wait_for_timeout(4000)
    ctx.close(); b.close()

uniq = list(dict.fromkeys(ids))
print("PAGES", pages, "RAW", len(ids), "UNIQ", len(uniq))
print("IDSAMPLE", uniq[:3])
