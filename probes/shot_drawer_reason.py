
import json, os, sys, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = os.path.join(ROOT, ".onefeed", "tmp")
from playwright.sync_api import sync_playwright
BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8791")
feed = json.load(urllib.request.urlopen(BASE + "/api/feed?limit=60"))
target = next(i for i in feed["items"] if i.get("reasons"))
print("target:", target["platform"], target["reasons"], target["title"][:30])
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 960})
    pg.goto(BASE + "/", wait_until="networkidle", timeout=45000)
    pg.wait_for_timeout(800)
    pg.locator("article").filter(has_text=target["title"][:12]).first.click()
    pg.wait_for_timeout(1600)
    chips = pg.evaluate("() => [...document.querySelectorAll('aside span')].map(s => s.innerText.trim()).filter(t => t.includes('热度'))")
    print("drawer chips:", chips)
    pg.screenshot(path=os.path.join(ROOT, "design", "ui-drawer-reason.png"))
    b.close()
