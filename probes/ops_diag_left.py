
"""左栏收放的长任务归因：分别关掉宽度过渡 / 卡片重排 / 圆角阴影，各量一次。"""
from __future__ import annotations

import json, os, sys
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
  const P = window.__p = {frames: [], long: [], running: false, t0: 0};
  const rec = t => { if (!P.running) return; P.frames.push(t); requestAnimationFrame(rec); };
  try {
    new PerformanceObserver(list => { for (const e of list.getEntries()) P.long.push({d: e.duration, n: (e.attribution||[]).map(a=>a.name).join(",")}); })
      .observe({type: 'longtask', buffered: true});
  } catch (e) {}
  P.start = () => { P.frames = []; P.long = []; P.running = true; P.t0 = performance.now(); requestAnimationFrame(rec); };
  P.stop = () => {
    P.running = false;
    const f = P.frames, d = [];
    for (let i = 1; i < f.length; i++) d.push(f[i] - f[i-1]);
    const l = P.long.filter(x => true);
    return {n: d.length, max: d.length ? +Math.max(...d).toFixed(1) : 0, jank: d.filter(x => x > 33).length,
      longMs: +l.reduce((a, x) => a + x.d, 0).toFixed(1), longMax: l.length ? +Math.max(...l.map(x => x.d)).toFixed(1) : 0,
      longN: l.length};
  };
}
"""


def measure(page, name, action, wait=800):
    page.evaluate(INIT)
    page.wait_for_timeout(120)
    page.evaluate("window.__p.start()")
    action()
    page.wait_for_timeout(wait)
    st = page.evaluate("window.__p.stop()")
    print(f"{name:34s} max={st['max']:>6} jank={st['jank']} long={st['longMs']}/{st['longMax']} n={st['longN']}", flush=True)
    return st


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(1500)

    collapse = lambda: page.locator('button[title*="收起"], button[aria-label*="收起"]').first.click()
    expand = lambda: page.locator('button[title*="展开"], button[aria-label*="展开"]').first.click()

    for label, css in [
        ("基线", ""),
        ("关宽度过渡", ".shell-col{transition:none !important}"),
        ("卡片跳过圆角阴影", ".card-pad{border-radius:0 !important;box-shadow:none !important}"),
        ("卡片 content-visibility", "[data-vt-item]{content-visibility:auto;contain-intrinsic-size:auto 340px}"),
        ("关过渡+卡片CV", ".shell-col{transition:none !important} [data-vt-item]{content-visibility:auto;contain-intrinsic-size:auto 340px}"),
    ]:
        page.add_style_tag(content=css) if css else None
        measure(page, "collapse/" + label, collapse)
        page.wait_for_timeout(600)
        measure(page, "expand/" + label, expand)
        page.wait_for_timeout(600)
    b.close()
