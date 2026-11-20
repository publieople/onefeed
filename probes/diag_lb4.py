
import os, sys, json, base64
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(ROOT/".onefeed"/"tmp")
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAAJUlEQVR4nO3BAQ0AAADCoPdPbQ8HFAAAAAAAAAAAAAAAAAAAAAB4NBMAAAHr3O0yAAAAAElFTkSuQmCC")
BODY = {"supported": True, "detail": {"body": "这是正文占位内容", "images": [
    {"url": "http://127.0.0.1:8799/api/media/x/img-0"}, {"url": "http://127.0.0.1:8799/api/media/x/img-1"},
    {"url": "http://127.0.0.1:8799/api/media/x/img-2"}],
    "media": None, "stats": {}, "note": None, "comments": []}}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_context(viewport={"width":1440,"height":900}).new_page()
    errs=[]
    pg.on("console", lambda m: errs.append((m.type, m.text[:150])) if m.type in ("error","warning") else None)
    pg.on("pageerror", lambda e: errs.append(("pageerror", str(e)[:200])))
    pg.route("**/detail*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(BODY)))
    pg.route("**/api/media/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    pg.goto("http://127.0.0.1:8799/?p=bilibili", wait_until="load")
    pg.wait_for_timeout(1200)
    idv = pg.evaluate("""() => document.querySelector('a[href^="/item/"]').getAttribute('href').split('/item/')[1]""")
    pg.goto("http://127.0.0.1:8799/item/" + idv, wait_until="load")
    pg.wait_for_timeout(3000)
    print("errors:", errs[:6])
    print("DOM:", pg.evaluate("""() => { const m=document.querySelector('main'); const c=m.querySelector('[data-content]')||m;
       return c.innerHTML.replace(/<svg[\s\S]*?<\/svg>/g,'<svg/>').slice(0, 900); }"""))
    b.close()
