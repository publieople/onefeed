
import json
from urllib.parse import unquote
from playwright.sync_api import sync_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
urls = []
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True, args=["--disable-blink-features=AutomationControlled"])
    ctx = b.new_context(locale="zh-CN", viewport={"width":1440,"height":900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
    page = ctx.new_page()
    page.on("request", lambda req: urls.append(req.url))
    page.goto("https://www.douyin.com/jingxuan", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    raw = page.evaluate("() => { const e=document.querySelector('#RENDER_DATA'); return e? e.textContent : '' }")
    ctx.close(); b.close()

data = json.loads(unquote(raw))
print("TOPKEYS", list(data.keys())[:15])
def walk(o, path="", depth=0):
    if depth > 3: return
    if isinstance(o, dict):
        for k, v in list(o.items())[:20]:
            if k in ("awemeList","aweme_list","itemList","data","list") and isinstance(v, list) and v:
                print("FOUND", path + "/" + k, "len", len(v))
                it = v[0]
                if isinstance(it, dict):
                    print("  item keys:", list(it.keys())[:25])
            walk(v, path + "/" + k, depth + 1)
    elif isinstance(o, list):
        for i, v in enumerate(o[:3]): walk(v, path + f"[{i}]", depth + 1)
walk(data)
print("--- request urls with web/api ---")
for u in urls:
    if any(k in u for k in ("/aweme/v1/web/","/web/api/")):
        print(u.split("?")[0][:110])
