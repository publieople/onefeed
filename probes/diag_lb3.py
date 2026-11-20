
import os, sys, json, base64
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(ROOT/".onefeed"/"tmp")
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAAJUlEQVR4nO3BAQ0AAADCoPdPbQ8HFAAAAAAAAAAAAAAAAAAAAAB4NBMAAAHr3O0yAAAAAElFTkSuQmCC")
BODY = {"supported": True, "detail": {"body": "这是正文占位内容", "images": [
    {"url": "http://127.0.0.1:8799/api/media/x/img-0", "width": 600, "height": 800},
    {"url": "http://127.0.0.1:8799/api/media/x/img-1", "width": 600, "height": 800},
    {"url": "http://127.0.0.1:8799/api/media/x/img-2", "width": 600, "height": 800}],
    "media": None, "stats": {}, "note": None, "comments": [], "author": None, "title": "t"}}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_context(viewport={"width":1440,"height":900}).new_page()
    pg.route("**/detail*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(BODY)))
    pg.route("**/api/media/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    pg.goto("http://127.0.0.1:8799/?p=bilibili", wait_until="load")
    pg.wait_for_timeout(1500)
    idv = pg.evaluate("""() => document.querySelector('a[href^="/item/"]').getAttribute('href').split('/item/')[1]""")
    probe = pg.evaluate("""async (id) => { const r = await fetch('/api/item/' + id + '/detail'); const j = await r.json();
        return {imgs: (j.detail && j.detail.images || []).length, body: (j.detail||{}).body}; }""", idv)
    print("in-page fetch:", probe)
    pg.goto("http://127.0.0.1:8799/item/" + idv, wait_until="load")
    pg.wait_for_timeout(2800)
    print("page:", pg.evaluate("""() => ({lb: document.querySelectorAll('[data-lb-index]').length,
        imgs: [...document.querySelectorAll('main img')].map(i => i.src.slice(0,60)),
        hasBody: document.body.innerText.includes('正文占位')})"""))
    b.close()
