
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
    page.goto("http://127.0.0.1:8799/", wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(1200)
    page.locator('button[aria-label="更多操作"]').first.click()
    page.wait_for_timeout(400)
    print(page.evaluate("""() => {
      const m = document.querySelector('[role=menu]');
      if (!m) return {menu: null};
      const r = m.getBoundingClientRect();
      return {menu: m.innerText, rect: [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)],
        role: m.getAttribute('role'), cls: m.className.slice(0,120),
        items: [...m.querySelectorAll('*')].filter(e => e.getAttribute('role')==='menuitem').map(e => e.innerText + '|' + e.getAttribute('aria-disabled')),
        allButtons: [...m.querySelectorAll('button')].map(e => (e.innerText||e.getAttribute('aria-label')||'').replace(/\s+/g,' ').trim())};
    }"""))
    # 焦点在谁身上
    print("focus:", page.evaluate("() => document.activeElement && (document.activeElement.innerText||document.activeElement.getAttribute('aria-label')||document.activeElement.tagName)"))
    b.close()
