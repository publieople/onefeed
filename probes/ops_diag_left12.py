
"""连做 4 轮收放，看长任务是否稳定落在「展开」一侧。"""
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
    return {max: d.length ? +Math.max(...d).toFixed(1) : 0, long: +P.long.reduce((a,x)=>a+x,0).toFixed(0), n: P.long.length};
  };
}
"""
def measure(page, name, action, wait=800):
    page.evaluate(INIT); page.wait_for_timeout(120)
    page.evaluate("window.__p.start()"); action(); page.wait_for_timeout(wait)
    st = page.evaluate("window.__p.stop()")
    print(f"{name:22s} max={st['max']:>6} long={st['long']:>4} n={st['n']}", flush=True)

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(2000)
    for i in range(1, 5):
        measure(page, f"r{i}/collapse", lambda: page.locator('button[title*="收起"], button[aria-label*="收起"]').first.click())
        page.wait_for_timeout(600)
        measure(page, f"r{i}/expand", lambda: page.locator('button[title*="展开"], button[aria-label*="展开"]').first.click())
        page.wait_for_timeout(600)
    b.close()
