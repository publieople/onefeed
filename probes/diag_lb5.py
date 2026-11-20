
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
    pg.route("**/detail*", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(BODY)))
    pg.route("**/api/media/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    pg.goto("http://127.0.0.1:8799/?p=bilibili", wait_until="load"); pg.wait_for_timeout(1200)
    idv = pg.evaluate("""() => document.querySelector('a[href^="/item/"]').getAttribute('href').split('/item/')[1]""")
    pg.goto("http://127.0.0.1:8799/item/" + idv, wait_until="load"); pg.wait_for_timeout(2000)
    pg.get_by_role("button", name="原文").first.click(); pg.wait_for_timeout(1200)
    n = pg.locator("[data-lb-index]").count()
    print("原文 tab 缩略图:", n)
    if n >= 3:
        pg.locator('[data-lb-index="1"]').click(); pg.wait_for_timeout(800)
        st = pg.evaluate("""() => ({ov: getComputedStyle(document.body).overflow,
           idx: (document.body.innerText.match(/(\\d+) \\/ (\\d+)/)||[])[0]||null,
           dlg: document.querySelectorAll('[role=dialog]').length})""")
        print("打开灯箱:", st)
        pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(500)
        print("→ 之后:", pg.evaluate("""() => (document.body.innerText.match(/(\\d+) \\/ (\\d+)/)||[])[0]||null"""))
        pg.keyboard.press("Escape"); pg.wait_for_timeout(700)
        print("Esc 之后 overflow:", pg.evaluate("() => getComputedStyle(document.body).overflow"),
              "focus:", pg.evaluate("() => { const a=document.activeElement; return a && (a.getAttribute('data-lb-index') || a.tagName); }"))
        # 点击遮罩关闭
        pg.locator('[data-lb-index="0"]').click(); pg.wait_for_timeout(700)
        print("再开:", pg.evaluate("() => getComputedStyle(document.body).overflow"))
        pg.mouse.click(60, 60); pg.wait_for_timeout(600)
        print("点空白后:", pg.evaluate("() => getComputedStyle(document.body).overflow"))
    b.close()
