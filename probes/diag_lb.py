
import os, sys, json
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(ROOT/".onefeed"/"tmp")
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_context(viewport={"width":1440,"height":900}).new_page()
    pg.on("console", lambda m: print("  console:", m.type, m.text[:120]) if m.type=="error" else None)
    pg.goto("http://127.0.0.1:8801/item/xiaohongshu%3Anote%3A6aefeb59000000001802c758", wait_until="load")
    for w in (1000, 2000, 4000):
        pg.wait_for_timeout(w if w==1000 else 1000)
        st = pg.evaluate("""() => ({imgs: document.querySelectorAll('img').length, lb: document.querySelectorAll('[data-lb-index]').length,
          main: (document.querySelector('main')||document.body).innerText.replace(/\s+/g,' ').slice(0,200)})""")
        print(w, json.dumps(st, ensure_ascii=False)[:400])
    # 直接 open 一条信息流卡片进入，看是否同样
    b.close()
