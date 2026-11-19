import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8799"
sys.stdout.reconfigure(encoding="utf-8")

JS = """ () => {
  const lum = (c) => { const [r,g,b] = c.map(v => { v/=255; return v <= 0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); }); return 0.2126*r + 0.7152*g + 0.0722*b; };
  const parse = (s) => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(',').map(parseFloat); return { rgb: p.slice(0,3), a: p.length > 3 ? p[3] : 1 }; };
  const bgOf = (el) => { let n = el; while (n && n !== document.documentElement) { const s = getComputedStyle(n); const c = parse(s.backgroundColor); if (c && c.a > 0.9) return c.rgb; n = n.parentElement; } return [255,255,255]; };
  const res = { fade: 0, fadeSizes: {}, badgeBad: 0, badgeList: [] };
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const t = node.textContent.trim(); if (!t) continue;
    const el = node.parentElement; if (!el) continue;
    const s = getComputedStyle(el);
    if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) continue;
    const r = el.getBoundingClientRect(); if (r.width < 1 || r.height < 1 || r.top > innerHeight) continue;
    const fg = parse(s.color); if (!fg) continue;
    const bg = bgOf(el);
    const L1 = lum(fg.rgb), L2 = lum(bg);
    const ratio = (Math.max(L1,L2)+0.05)/(Math.min(L1,L2)+0.05);
    const isFade = Math.abs(fg.rgb[0]-154) < 2 && Math.abs(fg.rgb[1]-161) < 2 && Math.abs(fg.rgb[2]-171) < 2;
    if (isFade) { res.fade++; res.fadeSizes[s.fontSize] = (res.fadeSizes[s.fontSize]||0)+1; }
    // 徽章：白字 + 该元素自身不透明品牌底色
    const ownBg = parse(s.backgroundColor);
    if (ratio < 4.5 && ownBg && ownBg.a > 0.9 && fg.rgb.every(v => v > 240)) {
      res.badgeBad++; res.badgeList.push({ t: t.slice(0,10), size: s.fontSize, ratio: +ratio.toFixed(2), bg: ownBg.rgb.join(',') });
    }
  }
  return res;
} """
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    out = {}
    for path in ["/", "/settings", "/market"]:
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(BASE + path, wait_until="networkidle"); page.wait_for_timeout(1600)
        out[path] = page.evaluate(JS)
        ctx.close()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    b.close()
