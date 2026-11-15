
import os, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
TMP = os.path.join(ROOT, ".onefeed", "tmp")
os.makedirs(TMP, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = TMP
from playwright.sync_api import sync_playwright
BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8791")
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 960})
    pg.goto(BASE + "/", wait_until="networkidle", timeout=45000)
    pg.wait_for_timeout(800)
    # 只看小红书，确认图文宫格
    pg.locator("button").filter(has_text=re.compile(r"^小红书\s*\d+$")).first.click()
    pg.wait_for_timeout(1800)
    pg.screenshot(path=os.path.join(ROOT, "design", "ui-feed-xhs.png"))
    print("chips:", pg.evaluate("() => [...document.querySelectorAll('section button')].filter(b => b.innerText.trim()).map(b => b.innerText.replace(/\\s+/g,' ').trim() + '@' + Math.round(b.getBoundingClientRect().y)).slice(0, 12)"))
    b.close()
