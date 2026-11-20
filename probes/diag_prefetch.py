
import os, sys, json
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(ROOT/".onefeed"/"tmp")
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
BASE="http://127.0.0.1:8799"
with sync_playwright() as p:
    b=p.chromium.launch(channel="chrome", headless=True)
    pg=b.new_context(viewport={"width":1440,"height":900}).new_page()
    reqs=[]
    pg.on("request", lambda r: reqs.append(r.url.replace(BASE,"")) if "/api/item/" in r.url or "/api/media" in r.url else None)
    pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(2500)
    reqs.clear()
    cards = pg.locator('a[href^="/item/"]')
    boxes = [cards.nth(i).bounding_box() for i in range(6)]
    for bx in boxes:
        pg.mouse.move(bx["x"]+40, bx["y"]+40, steps=3)
        pg.wait_for_timeout(320)   # 跨过 260ms 预取阈值
    pg.wait_for_timeout(900)
    print("悬停 6 张卡的请求数:", len(reqs))
    for u in reqs[:12]: print("   ", u[:100])
    # 快速划过（<260ms）是否也触发
    reqs.clear()
    for bx in boxes:
        pg.mouse.move(bx["x"]+40, bx["y"]+40, steps=1)
        pg.wait_for_timeout(80)
    pg.wait_for_timeout(900)
    print("快速划过 6 张卡的请求数:", len(reqs))
    b.close()
