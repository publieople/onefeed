
import os, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT/".onefeed"/"tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
BASE="http://127.0.0.1:8799"; out={}
with sync_playwright() as p:
    b=p.chromium.launch(channel="chrome", headless=True)
    ctx=b.new_context(viewport={"width":1440,"height":900}); pg=ctx.new_page()
    pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]'); pg.wait_for_timeout(600)
    # 找带图正文的条目：进前 4 个详情，统计正文图与 CLS
    hrefs = pg.evaluate("() => [...document.querySelectorAll('main a[href^=\"/item/\"]')].slice(0,4).map(a=>a.getAttribute('href'))")
    rows=[]
    for h in hrefs:
        pg.goto(BASE+h, wait_until="load"); pg.wait_for_selector("h1", timeout=15000); pg.wait_for_timeout(1200)
        r = pg.evaluate("""() => {
          const imgs=[...document.querySelectorAll('[data-content] img')];
          const shifts = window.__cls || 0;
          return {imgs: imgs.length,
            noDim: imgs.filter(i=>!i.getAttribute('width')||!i.getAttribute('height')).length,
            http: imgs.filter(i=>i.currentSrc.startsWith('http:')).length,
            cls: performance.getEntriesByType('layout-shift').reduce((s,e)=> s + (e.hadRecentInput?0:e.value), 0),
            cardImgs: [...document.querySelectorAll('main img')].slice(0,3).map(i=>({l:i.loading, d:i.decoding, fp:i.fetchPriority}))};
        }""")
        rows.append(r)
    out["details"]=rows
    print(json.dumps(out, ensure_ascii=False, indent=1)[:2000])
    b.close()
