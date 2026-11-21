"""reduce-motion 下引擎必须不接管：滚轮回落成浏览器原生，一格 100px。"""
from playwright.sync_api import sync_playwright

SAMPLER = r"""
() => {
  window.__s = [];
  let last = null;
  const loop = (t) => {
    const y = window.scrollY;
    if (last === null || y !== last) window.__s.push({ t: Math.round(t), y });
    last = y;
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
    pg.goto("http://127.0.0.1:8799/", wait_until="domcontentloaded")
    pg.wait_for_timeout(2500)
    pg.mouse.move(700, 500)
    pg.evaluate(SAMPLER)
    pg.mouse.wheel(0, 100)
    pg.wait_for_timeout(600)
    rows = pg.evaluate("() => window.__s")
    print("reduce page 1x100:", rows[:8], "frames", len(rows))
    b.close()
