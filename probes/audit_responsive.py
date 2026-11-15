
import collections, os, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP = os.path.join(ROOT, ".onefeed", "tmp")
os.makedirs(TMP, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = TMP
from playwright.sync_api import sync_playwright
BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8791")
JS = "() => [...document.querySelectorAll('article')].map(a => { const r = a.getBoundingClientRect(); const m = a.querySelector('[data-media]'); return { h: Math.round(r.height*10)/10, w: Math.round(r.width), mh: m ? Math.round(m.getBoundingClientRect().height) : 0 }; })"
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    for width in (1440, 1100, 820, 640):
        pg = b.new_page(viewport={"width": width, "height": 900})
        pg.goto(BASE + "/", wait_until="networkidle", timeout=45000)
        pg.wait_for_timeout(900)
        cards = pg.evaluate(JS)
        hs = sorted({c["h"] for c in cards})
        ws = sorted({c["w"] for c in cards})
        mh = sorted({c["mh"] for c in cards})
        print(f"viewport={width:5d} n={len(cards):3d} 卡宽={ws} 媒体高={mh} 卡高={hs}")
        pg.screenshot(path=os.path.join(ROOT, "design", f"ui-feed-{width}.png"))
        pg.close()
    b.close()
