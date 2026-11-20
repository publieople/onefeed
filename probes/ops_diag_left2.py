
"""左栏收放：每个变体一个新页面，避免前一变体的样式残留（上一版就吃过这个亏）。"""
from __future__ import annotations

import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")

INIT = r"""
() => {
  if (window.__p) return;
  const P = window.__p = {frames: [], long: [], running: false};
  const rec = t => { if (!P.running) return; P.frames.push(t); requestAnimationFrame(rec); };
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) P.long.push(e.duration); })
    .observe({type: 'longtask', buffered: true}); } catch (e) {}
  P.start = () => { P.frames = []; P.long = []; P.running = true; requestAnimationFrame(rec); };
  P.stop = () => {
    P.running = false;
    const f = P.frames, d = [];
    for (let i = 1; i < f.length; i++) d.push(f[i] - f[i-1]);
    return {max: d.length ? +Math.max(...d).toFixed(1) : 0, jank: d.filter(x => x > 33).length,
      longMs: +P.long.reduce((a, x) => a + x, 0).toFixed(1), longMax: P.long.length ? +Math.max(...P.long).toFixed(1) : 0,
      longN: P.long.length};
  };
}
"""

VARIANTS = [
    ("基线", ""),
    ("卡片CV", "[data-vt-item]{content-visibility:auto;contain-intrinsic-size:auto 340px}"),
    ("卡片CV+contain:layout", "[data-vt-item]{content-visibility:auto;contain-intrinsic-size:auto 340px;contain:layout paint}"),
    ("卡片 contain:layout", "[data-vt-item]{contain:layout paint}"),
    ("关容器查询", ".card-pad{padding:12px !important} .card-title{font-size:15px !important} .card-meta{font-size:12px !important}"),
]


def measure(page, name, action, wait=900):
    page.evaluate(INIT)
    page.wait_for_timeout(150)
    page.evaluate("window.__p.start()")
    action()
    page.wait_for_timeout(wait)
    st = page.evaluate("window.__p.stop()")
    print(f"{name:30s} max={st['max']:>6} jank={st['jank']:>2} long={st['longMs']}/{st['longMax']} n={st['longN']}", flush=True)


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    for label, css in VARIANTS:
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page = ctx.new_page()
        page.goto(BASE + "/", wait_until="load")
        page.wait_for_selector('a[href^="/item/"]', timeout=25000)
        page.wait_for_timeout(1500)
        if css:
            page.add_style_tag(content=css)
            page.wait_for_timeout(400)
        measure(page, label + "/collapse", lambda: page.locator('button[title*="收起"], button[aria-label*="收起"]').first.click())
        page.wait_for_timeout(700)
        measure(page, label + "/expand", lambda: page.locator('button[title*="展开"], button[aria-label*="展开"]').first.click())
        ctx.close()
    b.close()
