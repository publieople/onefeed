
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
    ctx=b.new_context(viewport={"width":1440,"height":900})
    pg=ctx.new_page()
    sizes={}
    def on_resp(r):
        if r.request.resource_type=="image":
            try: n=len(r.body())
            except Exception: n=0
            sizes[r.url]=n
    pg.on("response", on_resp)
    pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]'); pg.wait_for_timeout(2500)
    imgs=pg.evaluate("""() => [...document.querySelectorAll('img')].slice(0,40).map(i => ({src: i.currentSrc || i.src, nw: i.naturalWidth, nh: i.naturalHeight, cw: Math.round(i.getBoundingClientRect().width), ch: Math.round(i.getBoundingClientRect().height), cls: String(i.className).slice(0,30)}))""")
    def cat(u):
        if "avatar" in u or "/face/" in u or "passport" in u: return "avatar"
        return "cover"
    agg={}
    for u,n in sizes.items():
        c=cat(u); a=agg.setdefault(c,{"n":0,"bytes":0,"max":0}); a["n"]+=1; a["bytes"]+=n; a["max"]=max(a["max"],n)
    out["image_bytes"]=agg
    out["waste"]=[{ **i, "bytes": sizes.get(i["src"], 0)} for i in imgs if i["nw"] > i["cw"]*1.8][:8]
    out["oversize_count"]=sum(1 for i in imgs if i["nw"] > i["cw"]*1.8)
    out["img_total"]=len(imgs)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
    b.close()
