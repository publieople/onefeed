"""Lenis 调校版滚动手感：逐帧采样，看首帧步进、总帧数、收尾时间与边界接力。"""
import json, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
SAMPLER = r"""
() => {
  window.__s = [];
  let last = null, stop = false;
  const loop = (t) => {
    if (stop) return;
    const box = document.querySelector('[data-smooth-scroll]');
    const side = box ? Math.round(box.scrollTop) : -1;
    const page = Math.round(window.scrollY);
    if (last === null || side !== last.side || page !== last.page) {
      window.__s.push({ t: Math.round(t), side, page });
    }
    last = { side, page };
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  window.__stop = () => { stop = true; };
}
"""

def summarize(label, samples, start_ms, key):
    pts = [(s["t"] - start_ms, s[key]) for s in samples]
    pts = [(t, v) for t, v in pts if t >= 0]
    if not pts:
        print(f"--- {label}: no frames"); return
    base = pts[0][1]
    moved = [(t, v - base) for t, v in pts if v != base]
    if not moved:
        print(f"--- {label}: no movement (base {base})"); return
    steps = []
    prev = 0
    for t, d in moved:
        steps.append(d - prev); prev = d
    print(f"--- {label}: {len(moved)} 帧变化 / 用时 {moved[-1][0]}ms / 总位移 {moved[-1][1]}px / 最大单步 {max(steps)}px")
    print("   ", json.dumps([(t, v) for t, v in moved[:14]], ensure_ascii=False))

def run(pg, label, action, key, wait_ms=1100):
    pg.evaluate(SAMPLER)
    t0 = pg.evaluate("() => Math.round(performance.now())")
    action()
    pg.wait_for_timeout(wait_ms)
    samples = pg.evaluate("() => window.__s")
    pg.evaluate("() => window.__stop()")
    summarize(label, samples, t0, key)

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    pg.goto("http://127.0.0.1:8799/", wait_until="domcontentloaded")
    pg.wait_for_timeout(2500)

    box = pg.evaluate("""() => { const el = document.querySelector('[data-smooth-scroll]'); if(!el) return null; el.scrollTop = 0; const r = el.getBoundingClientRect(); return {x: r.x + r.width/2, y: r.y + r.height/2, max: el.scrollHeight - el.clientHeight}; }""")
    print("sidebar box", box)
    pg.mouse.move(box["x"], box["y"])
    run(pg, "sidebar 1 tick", lambda: pg.mouse.wheel(0, 100), "side")
    pg.evaluate("() => { document.querySelector('[data-smooth-scroll]').scrollTop = 0; window.scrollTo(0, 0); }")
    pg.wait_for_timeout(600)
    run(pg, "sidebar 3 ticks x400", lambda: [(pg.mouse.wheel(0, 400), pg.wait_for_timeout(60)) for _ in range(3)], "side")

    pg.evaluate("() => { document.querySelector('[data-smooth-scroll]').scrollTop = 0; window.scrollTo(0, 0); }")
    pg.wait_for_timeout(600)
    pg.mouse.move(700, 600)
    run(pg, "page 1 tick", lambda: pg.mouse.wheel(0, 100), "page")
    pg.evaluate("() => window.scrollTo(0, 0)")
    pg.wait_for_timeout(600)

    # 边界接力：侧栏拉到底，再滚一格，应该由页面接着走
    pg.evaluate("""() => { const el = document.querySelector('[data-smooth-scroll]'); el.scrollTop = el.scrollHeight; window.scrollTo(0, 0); }""")
    pg.wait_for_timeout(400)
    pg.mouse.move(box["x"], box["y"])
    run(pg, "sidebar bottom -> page", lambda: pg.mouse.wheel(0, 400), "page")

    # 空闲时 rAF 是否停掉
    idle = pg.evaluate("""() => new Promise((res) => { let n = 0; const loop = () => { n++; requestAnimationFrame(loop); }; requestAnimationFrame(loop); setTimeout(() => res(n), 1000); })""")
    print("rAF callbacks in 1s (idle):", idle)
    b.close()
