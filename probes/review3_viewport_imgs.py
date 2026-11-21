
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
    sizes={}
    pg.on("response", lambda r: sizes.__setitem__(r.url, len(r.body()) if r.request.resource_type=="image" else 0) if r.request.resource_type=="image" else None)
    pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]'); pg.wait_for_timeout(3000)
    rows = pg.evaluate("""() => [...document.querySelectorAll('main img')].filter(i => {const r=i.getBoundingClientRect(); return r.bottom>0 && r.top<innerHeight && r.width>40;}).map(i => {
        const r=i.getBoundingClientRect(); return {src:i.currentSrc||i.src, cw:Math.round(r.width), ch:Math.round(r.height), nw:i.naturalWidth, nh:i.naturalHeight, loading:i.loading, fp:i.fetchPriority}; })""")
    total=0; items=[]
    for r in rows:
        n=sizes.get(r["src"],0); total+=n
        items.append({**r, "kb": round(n/1024)})
    out={"viewport_imgs": len(items), "total_kb": round(total/1024), "items": items}
    print(json.dumps(out, ensure_ascii=False, indent=1)[:2500])
    b.close()
