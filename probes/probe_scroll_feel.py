"""滚轮手感基线：逐帧采样 scrollTop，量化起手延迟 / 步进 / 拖尾。"""
import json, os, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SAMPLER = r"""
() => {
  window.__samples = [];
  let last = null, stop = false;
  const loop = (t) => {
    if (stop) return;
    const box = document.querySelector('[data-smooth-scroll]');
    const side = box ? box.scrollTop : -1;
    const page = window.scrollY;
    if (last === null || side !== last.side || page !== last.page) {
      window.__samples.push({ t: Math.round(t), side, page });
    }
    last = { side, page };
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  window.__stopSampler = () => { stop = true; };
}
"""

def run(page, label, action, wait_ms=900):
    page.evaluate(SAMPLER.replace("() =>", "() =>", 1))
    t0 = time.perf_counter()
    action()
    page.wait_for_timeout(wait_ms)
    samples = page.evaluate("() => window.__samples")
    page.evaluate("() => window.__stopSampler && window.__stopSampler()")
    side = [s for s in samples]
    print(f"--- {label}: {len(side)} 个变化帧")
    print(json.dumps(side[:40], ensure_ascii=False))
    if side:
        print("  first", side[0], "last", side[-1])
    return side

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    pg.goto("http://127.0.0.1:8799/", wait_until="domcontentloaded")
    pg.wait_for_timeout(2500)

    box = pg.evaluate("""() => { const el = document.querySelector('[data-smooth-scroll]'); if(!el) return null; el.scrollTop = 0; const r = el.getBoundingClientRect(); return {x: r.x + r.width/2, y: r.y + r.height/2, h: el.scrollHeight, c: el.clientHeight}; }""")
    print("sidebar box", box)
    if box:
        pg.mouse.move(box["x"], box["y"])
        run(pg, "sidebar 1 tick", lambda: pg.mouse.wheel(0, 100))
        pg.evaluate("() => { const el = document.querySelector('[data-smooth-scroll]'); el.scrollTop = 0; }")
        pg.wait_for_timeout(300)
        run(pg, "sidebar 3 ticks x400", lambda: [ (pg.mouse.wheel(0, 400), pg.wait_for_timeout(60)) for _ in range(3) ])

    pg.evaluate("() => window.scrollTo(0, 0)")
    pg.wait_for_timeout(300)
    pg.mouse.move(700, 500)
    run(pg, "page 1 tick", lambda: pg.mouse.wheel(0, 100))
    pg.evaluate("() => window.scrollTo(0, 0)")
    pg.wait_for_timeout(300)
    run(pg, "page 3 ticks x400", lambda: [ (pg.mouse.wheel(0, 400), pg.wait_for_timeout(60)) for _ in range(3) ])
    b.close()
