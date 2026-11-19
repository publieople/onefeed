import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8799"
OUT = ROOT / "design" / "review"
sys.stdout.reconfigure(encoding="utf-8")

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle")
    page.wait_for_timeout(1500)
    print("labels", json.dumps(page.evaluate("() => [...new Set([...document.querySelectorAll('[aria-label]')].map(e => e.getAttribute('aria-label')))]"), ensure_ascii=False))
    info = page.evaluate(""" () => {
      const cands = [...document.querySelectorAll('div, nav')].filter(e => e.querySelectorAll('button').length >= 6 && e.querySelectorAll('button').length <= 12);
      return cands.slice(0, 3).map(e => {
        const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
        return { cls: e.className.slice(0,90), btns: e.querySelectorAll('button').length, w: Math.round(r.width), sw: e.scrollWidth,
                 overflowX: s.overflowX, scrollW: e.scrollWidth, clientW: e.clientWidth, role: e.getAttribute('role') };
      });
    } """)
    print("rail candidates", json.dumps(info, ensure_ascii=False, indent=1))
    chip = page.evaluate(""" () => {
      const btn = [...document.querySelectorAll('button')].find(b => b.getAttribute('aria-pressed') === 'true');
      if (!btn) return null;
      const s = getComputedStyle(btn);
      const parent = btn.parentElement;
      const spans = [...parent.querySelectorAll('span')].map(x => { const t = getComputedStyle(x); return { bg: t.backgroundColor, op: t.opacity, cls: x.className.slice(0,40) }; });
      return { text: btn.innerText.trim().slice(0,10), color: s.color, bg: s.backgroundColor, spans: spans.slice(0,4) };
    } """)
    print("chip light", json.dumps(chip, ensure_ascii=False))
    page.click('button[aria-label^="切换到"]')
    page.wait_for_timeout(600)
    chip = page.evaluate(""" () => {
      const btn = [...document.querySelectorAll('button')].find(b => b.getAttribute('aria-pressed') === 'true');
      if (!btn) return null;
      const s = getComputedStyle(btn);
      const parent = btn.parentElement;
      const spans = [...parent.querySelectorAll('span')].map(x => { const t = getComputedStyle(x); return { bg: t.backgroundColor, op: t.opacity }; });
      return { text: btn.innerText.trim().slice(0,10), color: s.color, bg: s.backgroundColor, spans: spans.slice(0,4) };
    } """)
    print("chip dark", json.dumps(chip, ensure_ascii=False))
    page.screenshot(path=str(OUT / "chips-dark.png"), clip={"x": 0, "y": 120, "width": 390, "height": 90})
    page.click('button[aria-label^="切换到"]')
    page.wait_for_timeout(300)
    # 内容被底部 AI dock 遮挡的高度
    print("dock", json.dumps(page.evaluate(""" () => {
      const form = document.querySelector('form');
      if (!form) return null;
      const r = form.getBoundingClientRect();
      return { top: Math.round(r.top), h: Math.round(r.height), vh: innerHeight, covers: Math.round(innerHeight - r.top) };
    } """)))
    b.close()
