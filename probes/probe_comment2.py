
import json
from playwright.sync_api import sync_playwright
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
seen = []
def on_resp(r):
    if "comment" in r.url:
        try: b = r.json()
        except Exception: b = None
        n = 0
        if isinstance(b, dict):
            for k in ("comments","data","reply_comments"):
                v = b.get(k)
                if isinstance(v, list): n = max(n, len(v))
        seen.append({"u": r.url.split("?")[0], "n": n, "status": r.status})
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROME, headless=False, args=["--disable-blink-features=AutomationControlled"])
    ctx = br.new_context(locale="zh-CN", viewport={"width":1440,"height":900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
    page = ctx.new_page(); page.on("response", on_resp)
    page.goto("https://www.douyin.com/video/7707124903274745139", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(7000)
    print("URL", page.url[:80])
    # 尝试点评论图标
    for sel in ['[data-e2e="feed-comment-icon"]', '[data-e2e="comment-icon"]', 'span:has-text("条评论")', '[class*="comment"]']:
        try:
            loc = page.locator(sel).first
            if loc.count():
                loc.click(timeout=3000); page.wait_for_timeout(4000); print("CLICKED", sel); break
        except Exception as e:
            pass
    page.wait_for_timeout(4000)
    ctx.close(); br.close()
print("SEEN", len(seen))
for s in seen[:12]: print(s["status"], s["n"], s["u"][:90])
