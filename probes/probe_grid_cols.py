
import os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
Q = """() => {
  const cards = document.querySelectorAll('[data-vt-item]');
  const first = cards[0];
  const grid = first ? first.parentElement : null;
  const cs = grid ? getComputedStyle(grid) : null;
  const main = document.querySelector('main');
  return {
    cols: cs ? cs.gridTemplateColumns.split(' ').length : null,
    gridW: grid ? Math.round(grid.getBoundingClientRect().width) : null,
    cardW: first ? Math.round(first.getBoundingClientRect().width) : null,
    mainW: main ? Math.round(main.getBoundingClientRect().width) : null,
    contentW: (() => { const c = document.querySelector('[data-content]'); return c ? Math.round(c.getBoundingClientRect().width) : null; })(),
    n: cards.length,
  };
}"""
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(1500)
    print("initial   ", page.evaluate(Q), flush=True)
    page.locator('button[title*="收起"], button[aria-label*="收起"]').first.click()
    page.wait_for_timeout(1200)
    print("collapsed ", page.evaluate(Q), flush=True)
    page.locator('button[title*="展开"], button[aria-label*="展开"]').first.click()
    page.wait_for_timeout(1200)
    print("expanded  ", page.evaluate(Q), flush=True)
    b.close()
