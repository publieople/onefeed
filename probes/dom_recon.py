
import json, os, sys
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP","TEMP","TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8799"

DUMP = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 2 && r.height > 2 && s.visibility !== 'hidden' && s.display !== 'none' && parseFloat(s.opacity) > 0.1; };
  const name = el => (el.getAttribute('aria-label') || el.title || (el.innerText||'').trim().replace(/\s+/g,' ').slice(0,28) || el.placeholder || el.tagName);
  const out = [];
  for (const el of document.querySelectorAll('button, a[href], input, textarea, select, [role=button], [role=tab], [tabindex]')) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    out.push({tag: el.tagName.toLowerCase(), name: name(el), role: el.getAttribute('role')||'',
      cls: (el.className||'').toString().slice(0,70),
      rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
      aria: {pressed: el.getAttribute('aria-pressed'), expanded: el.getAttribute('aria-expanded'), checked: el.getAttribute('aria-checked'), label: el.getAttribute('aria-label'), current: el.getAttribute('aria-current')}});
  }
  return out;
}
"""
res = {}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle")
    page.wait_for_selector('a[href^="/item/"]', timeout=20000)
    page.wait_for_timeout(800)
    res["feed"] = page.evaluate(DUMP)
    res["feed_html_sample"] = page.evaluate("() => document.querySelector('a[href^=\"/item/\"]').outerHTML.slice(0, 2600)")
    # 打开右栏抽屉页签 + 左栏标签
    page.click('a[href^="/item/"]')
    page.wait_for_url("**/item/**", timeout=15000)
    page.wait_for_timeout(2500)
    res["item"] = page.evaluate(DUMP)
    page.goto(BASE + "/settings", wait_until="networkidle"); page.wait_for_timeout(1200)
    res["settings"] = page.evaluate(DUMP)
    page.goto(BASE + "/market", wait_until="networkidle"); page.wait_for_timeout(1200)
    res["market"] = page.evaluate(DUMP)
    page.goto(BASE + "/agent", wait_until="networkidle"); page.wait_for_timeout(1200)
    res["agent"] = page.evaluate(DUMP)
    page.goto(BASE + "/nope", wait_until="networkidle"); page.wait_for_timeout(600)
    res["nope"] = page.evaluate(DUMP)
    b.close()
(ROOT / ".onefeed" / "dom-dump.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
for k, v in res.items():
    if k.endswith("sample"): continue
    print("=====", k, len(v))
    for e in v[:80]:
        print(" ", e["tag"], "|", e["name"][:40], "|", e["role"], "|", e["rect"], "|", e["aria"])