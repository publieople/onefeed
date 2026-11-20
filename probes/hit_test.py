
import os, sys, json
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP","TEMP","TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

HIT = r"""
(specs) => {
  const out = [];
  for (const s of specs) {
    const el = document.querySelector(s.sel);
    if (!el) { out.push({sel: s.sel, miss: true}); continue; }
    el.scrollIntoView({block: 'center'});
    const r = el.getBoundingClientRect();
    const x = r.x + r.width/2, y = r.y + r.height/2;
    const top = document.elementFromPoint(x, y);
    const chain = [];
    let n = top;
    for (let i = 0; n && i < 5; i++) { chain.push(n.tagName + '.' + (n.className||'').toString().slice(0,50)); n = n.parentElement; }
    const cs = top ? getComputedStyle(top) : null;
    out.push({sel: s.sel, label: s.label||'', rect: [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)],
      hitSelf: el === top || el.contains(top),
      top: top ? top.tagName + '.' + (top.className||'').toString().slice(0,60) : null,
      topPos: cs ? cs.position : null, topZ: cs ? cs.zIndex : null, topPE: cs ? cs.pointerEvents : null,
      topText: top ? (top.innerText||'').trim().slice(0,40) : null, chain});
  }
  return out;
}
"""
specs = [
  {"sel": 'button[title*="每行显示"]', "label": "列数按钮"},
  {"sel": 'button[aria-label="更多操作"]', "label": "三点菜单"},
  {"sel": 'button[aria-label="稍后再看"]', "label": "星标"},
  {"sel": 'a[href^="/item/"]', "label": "卡片"},
  {"sel": 'button[aria-label^="切换到"]', "label": "主题"},
  {"sel": 'button[aria-label="刷新全部平台"]', "label": "刷新"},
  {"sel": 'button[aria-pressed="true"]', "label": "分段控件首项"},
]
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_context(viewport={"width":1440,"height":900}).new_page()
    page.goto("http://127.0.0.1:8799/", wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(1500)
    res = page.evaluate(HIT, specs)
    print(json.dumps(res, ensure_ascii=False, indent=1)[:6000])
    # 直接试一次 Playwright 原生 click，看是否报错
    for sel in ['button[title*="每行显示"]', 'button[aria-label="更多操作"]']:
        try:
            page.locator(sel).first.click(timeout=4000)
            print("native click OK:", sel)
            page.wait_for_timeout(600)
            print("  popup?", page.evaluate("() => document.querySelectorAll('[role=menu]').length"), page.evaluate("() => document.querySelectorAll('[aria-haspopup]').length"))
            page.keyboard.press("Escape"); page.wait_for_timeout(300)
        except Exception as e:
            print("native click FAIL:", sel, str(e).splitlines()[0][:120])
    # 找灯箱触发元素
    page.goto("http://127.0.0.1:8799/?p=xiaohongshu", wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(1200)
    page.locator('a[href^="/item/"]').first.click()
    page.wait_for_timeout(3000)
    print("lb attrs:", page.evaluate("""() => {
      const cands = [...document.querySelectorAll('*')].filter(e => (e.getAttributeNames()||[]).some(a => a.includes('lb')));
      return {n: cands.length, sample: cands.slice(0,6).map(e => e.tagName + ' ' + e.getAttributeNames().join(',') + ' cls=' + (e.className||'').toString().slice(0,50)),
              imgs: document.querySelectorAll('main img').length,
              clickableImgs: [...document.querySelectorAll('main img')].map(i => i.closest('button,a') ? 'in-button' : (i.parentElement.className||'').toString().slice(0,40)).slice(0,8)};
    }"""))
    b.close()