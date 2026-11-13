
import json
from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
hits, seen = [], []

def on_resp(resp):
    u = resp.url
    if "/aweme/v1/web/tab/feed" in u or "/aweme/v1/web/feed" in u:
        try:
            body = resp.json()
        except Exception as e:
            seen.append({"status": resp.status, "err": str(e)[:60], "url": u[:100]})
            return
        items = body.get("aweme_list") or []
        seen.append({"status": resp.status, "n": len(items), "keys": list(body.keys())[:8]})
        for it in items:
            v = it.get("video") or {}
            cov = (v.get("cover") or {}).get("url_list") or (v.get("origin_cover") or {}).get("url_list") or []
            hits.append({"id": it.get("aweme_id"), "desc": (it.get("desc") or "")[:60],
                         "author": (it.get("author") or {}).get("nickname"),
                         "cover": cov[0][:110] if cov else None, "stat": it.get("statistics")})

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True,
                          args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(locale="zh-CN", viewport={"width":1440,"height":900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
    page = ctx.new_page(); page.on("response", on_resp)
    try:
        page.goto("https://www.douyin.com/?recommend=1", wait_until="domcontentloaded", timeout=45000)
    except Exception as e:
        print("GOTO_ERR", str(e)[:150])
    page.wait_for_timeout(7000)
    print("TITLE", page.title()[:60])
    print("URL", page.url[:100])
    print("RENDER_DATA_LEN", page.evaluate("() => { const e=document.querySelector('#RENDER_DATA'); return e? e.textContent.length:0 }"))
    page.mouse.wheel(0, 2500); page.wait_for_timeout(5000)
    print("RENDER_DATA_LEN2", page.evaluate("() => { const e=document.querySelector('#RENDER_DATA'); return e? e.textContent.length:0 }"))
    ctx.close(); b.close()

print("RESP", json.dumps(seen, ensure_ascii=False))
print("HITS", len(hits))
for h in hits[:6]: print(json.dumps(h, ensure_ascii=False)[:320])
