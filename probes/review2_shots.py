import os, sys
from pathlib import Path
ROOT = Path(".").resolve()
TMP = ROOT/".onefeed"/"tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(TMP)
SHOT = ROOT/".onefeed"/"shots"; SHOT.mkdir(parents=True, exist_ok=True)
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    br = pw.chromium.launch(channel="chrome", headless=True)
    page = br.new_page(viewport={"width":1440,"height":900})
    page.goto("http://127.0.0.1:8799/", wait_until="domcontentloaded")
    page.wait_for_selector("a[href^='/item/']", timeout=20000); page.wait_for_timeout(1600)
    b = page.evaluate("""() => { const n=[...document.querySelectorAll('button')].find(x=>((x.getAttribute('title')||'')+(x.getAttribute('aria-label')||'')).includes('收起 Agent')); const r=n.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
    box = {"x":0,"y":57,"width":420,"height":420}
    page.screenshot(path=str(SHOT/"rail-before.png"), clip=box)
    page.mouse.click(b["x"], b["y"])
    page.wait_for_timeout(110)
    page.screenshot(path=str(SHOT/"rail-mid110.png"), clip=box)
    page.wait_for_timeout(120)
    page.screenshot(path=str(SHOT/"rail-mid230.png"), clip=box)
    page.wait_for_timeout(600)
    page.screenshot(path=str(SHOT/"rail-after.png"), clip=box)
    print("saved", [p.name for p in SHOT.glob("rail-*.png")])
    br.close()
