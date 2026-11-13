
import json
from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
cands = []
def on_resp(resp):
    try:
        ct = (resp.headers or {}).get("content-type","")
        if "json" not in ct: return
        u = resp.url
        if "/aweme/v1/web/" not in u: return
        try:
            body = resp.json()
        except Exception:
            return
        s = json.dumps(body)[:200]
        cands.append({"url": u.split("?")[0], "status": resp.status, "len": len(s), "head": s[:120]})
    except Exception:
        pass

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(locale="zh-CN", viewport={"width":1440,"height":900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
    page = ctx.new_page(); page.on("response", on_resp)
    page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    for i in range(3):
        page.mouse.wheel(0, 3000); page.wait_for_timeout(3500)
    print("HTML_LEN", page.evaluate("() => document.body.innerText.length"))
    print("VIDEO_COUNT", page.evaluate("() => document.querySelectorAll('a[href*=\"/video/\"]').length"))
    ctx.close(); b.close()

print("CANDIDATES", len(cands))
seen=set()
for c in cands:
    k=c["url"]
    print(c["status"], c["len"], c["url"][:90], "|", c["head"][:80].replace("\n"," "))
