
import os, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT/".onefeed"/"tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
url = "http://127.0.0.1:8799/item/bilibili%3Avideo%3ABV1yRs462EFX"
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_context(viewport={"width":1440,"height":900}).new_page()
    pg.goto(url, wait_until="load")
    pg.wait_for_timeout(4000)
    info = pg.evaluate("""() => {
      const main = document.querySelector('main');
      const btns = [...document.querySelectorAll('button')].map(b => (b.getAttribute('aria-label')||b.innerText||'').trim().slice(0,24)).filter(Boolean);
      const text = main ? main.innerText : '';
      return {len: text.length, head: text.slice(0, 700), btns: [...new Set(btns)], iframes: document.querySelectorAll('iframe').length,
              videos: document.querySelectorAll('video').length, imgs: document.querySelectorAll('img').length};
    }""")
    print(json.dumps(info, ensure_ascii=False, indent=1)[:4000])
    b.close()
