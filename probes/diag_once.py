
import os, sys, json
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP","TEMP","TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_context(viewport={"width":1440,"height":900}).new_page()
    page.goto("http://127.0.0.1:8799/", wait_until="load", timeout=30000)
    page.wait_for_timeout(3000)
    print(page.evaluate("""() => ({
      items: document.querySelectorAll('[data-vt-item]').length,
      itemTags: [...new Set([...document.querySelectorAll('[data-vt-item]')].map(e=>e.tagName))],
      links: document.querySelectorAll('a[href^="/item/"]').length,
      firstCard: (document.querySelector('a[href^="/item/"]')||{}).outerHTML?.slice(0,900),
      vtNames: [...document.querySelectorAll('[data-vt]')].slice(0,6).map(e=>e.tagName+':'+e.getAttribute('data-vt')),
    })"""))
    b.close()
