"""设计评审实测探针：五档断点、亮暗两套截图 + 度量。"""
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
OUT = ROOT / "design" / "review"
OUT.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding="utf-8")

MEASURE = r"""
() => {
  const vis = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) > 0.05;
  };
  const out = {};
  out.scroll = { iw: innerWidth, sw: document.documentElement.scrollWidth, bw: document.body.scrollWidth };
  const fs = {}, radii = {}, shadows = {}, colors = {};
  const smallTargets = [];
  let focusables = 0, missingLabel = [];
  for (const el of document.querySelectorAll('*')) {
    if (!vis(el)) continue;
    const s = getComputedStyle(el);
    const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim().length > 0);
    if (hasText) {
      fs[s.fontSize] = (fs[s.fontSize] || 0) + 1;
      const key = s.color;
      colors[key] = (colors[key] || 0) + 1;
    }
    if (s.borderTopLeftRadius !== '0px' && s.borderTopLeftRadius !== '0') radii[s.borderTopLeftRadius] = (radii[s.borderTopLeftRadius]||0)+1;
    if (s.boxShadow !== 'none') shadows[s.boxShadow] = (shadows[s.boxShadow]||0)+1;
    if (el.matches('button, a[href], input, [role=button], [tabindex]:not([tabindex="-1"])')) {
      focusables++;
      const r = el.getBoundingClientRect();
      if (r.height < 44 || r.width < 44) smallTargets.push({
        tag: el.tagName, txt: (el.innerText||el.getAttribute('aria-label')||el.title||'').trim().slice(0,18),
        w: +r.width.toFixed(1), h: +r.height.toFixed(1)
      });
      const name = (el.innerText||'').trim() || el.getAttribute('aria-label') || el.title || el.alt;
      if (!name) missingLabel.push(el.tagName + '.' + (el.className||'').toString().slice(0,40));
    }
  }
  out.fontSizes = Object.entries(fs).sort((a,b)=>parseFloat(a[0])-parseFloat(b[0]));
  out.radii = Object.entries(radii).sort((a,b)=>parseFloat(b[1])-parseFloat(a[1])).slice(0,14);
  out.shadows = Object.entries(shadows).sort((a,b)=>b[1]-a[1]).slice(0,10);
  out.colors = Object.entries(colors).sort((a,b)=>b[1]-a[1]).slice(0,12);
  out.focusables = focusables;
  out.smallTargets = smallTargets.slice(0, 40);
  out.smallCount = smallTargets.length;
  out.missingLabel = missingLabel.slice(0, 20);
  out.headings = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h => h.tagName + ':' + h.innerText.trim().slice(0,26));
  out.imgsNoAlt = [...document.querySelectorAll('img')].filter(i => i.alt === '' || i.alt == null).length;
  out.imgs = document.querySelectorAll('img').length;
  out.buttons = document.querySelectorAll('button').length;
  out.ariaPressed = document.querySelectorAll('[aria-pressed]').length;
  out.articleCount = document.querySelectorAll('article').length;
  const h = [...document.querySelectorAll('article')].map(a => +a.getBoundingClientRect().height.toFixed(1));
  out.cardHeights = [...new Set(h)];
  return out;
}
"""

report = {"base": BASE, "views": {}}

def run_view(page, label, path, shot=True, full=False):
    page.goto(BASE + path, wait_until="networkidle")
    page.wait_for_timeout(1200)
    if path == "/":
        try:
            page.wait_for_selector("article", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(600)
    m = page.evaluate(MEASURE)
    report["views"][label] = m
    if shot:
        page.screenshot(path=str(OUT / (label + ".png")))
        if full:
            page.screenshot(path=str(OUT / (label + "-full.png")), full_page=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    for w, h, name in [(390, 844, "390"), (768, 1024, "768"), (1024, 768, "1024"), (1440, 900, "1440"), (1920, 1080, "1920")]:
        ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
        page = ctx.new_page()
        run_view(page, "feed-" + name + "-light", "/")
        if name in ("390", "1440", "1920"):
            page.click('button[aria-label^="切换到"]')
            page.wait_for_timeout(500)
            run_view(page, "feed-" + name + "-dark", "/")
            page.click('button[aria-label^="切换到"]')
            page.wait_for_timeout(300)
        if name in ("390", "1440"):
            run_view(page, "settings-" + name, "/settings", full=True)
            run_view(page, "market-" + name, "/market")
            page.goto(BASE + "/", wait_until="networkidle")
            page.wait_for_timeout(800)
            try:
                page.locator("article").first.click()
                page.wait_for_timeout(2500)
                report["views"]["item-" + name] = page.evaluate(MEASURE)
                page.screenshot(path=str(OUT / ("item-" + name + ".png")))
                page.screenshot(path=str(OUT / ("item-" + name + "-full.png")), full_page=True)
            except Exception as e:
                report["views"]["item-" + name] = {"error": str(e)}
        ctx.close()
    browser.close()

(OUT / "measure.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
for k, v in report["views"].items():
    if "error" in v:
        print(k, "ERROR", v["error"]); continue
    print(k, "scroll", v["scroll"], "cards", v["articleCount"], "heights", v["cardHeights"], "small", v["smallCount"], "/", v["focusables"])
print("saved", OUT)
