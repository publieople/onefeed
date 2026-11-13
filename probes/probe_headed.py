
import json
from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
found = []
def on_resp(resp):
    u = resp.url
    if "aweme" not in u and "feed" not in u: return
    try:
        body = resp.json()
    except Exception:
        return
    n = 0
    if isinstance(body, dict):
        for k in ("aweme_list","data","awemeList"):
            v = body.get(k)
            if isinstance(v, list): n = max(n, len(v))
    found.append({"url": u.split("?")[0], "n": n, "keys": list(body.keys())[:8] if isinstance(body, dict) else None})

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=False, args=["--disable-blink-features=AutomationControlled","--window-size=1440,900"])
    ctx = b.new_context(locale="zh-CN", viewport={"width":1440,"height":900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
    page = ctx.new_page(); page.on("response", on_resp)
    page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(8000)
    print("URL", page.url[:90])
    print("TITLE", page.title()[:50])
    print("VIDEO_LINKS", page.evaluate("() => document.querySelectorAll('a[href*=\"/video/\"]').length"))
    print("BODY_LEN", page.evaluate("() => document.body.innerText.length"))
    for i in range(2):
        page.mouse.wheel(0, 2500); page.wait_for_timeout(3000)
    print("VIDEO_LINKS2", page.evaluate("() => document.querySelectorAll('a[href*=\"/video/\"]').length"))
    ctx.close(); b.close()

print("CAPTURED", len(found))
for f in found[:15]:
    print(f["n"], f["url"][:80], f["keys"])
