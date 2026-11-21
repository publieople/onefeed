"""滚轮引擎回归：小 delta 触控板、路由切换漂移、模态锁。"""
import json, time
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8799"

SAMPLER = r"""
() => {
  window.__s = [];
  let last = null, stop = false;
  const loop = (t) => {
    if (stop) return;
    const y = window.scrollY;
    if (last === null || y !== last) window.__s.push({ t: Math.round(t), y });
    last = y;
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
  window.__stop = () => { stop = true; };
}
"""

def sample(pg, label, action, wait=700):
    pg.evaluate(SAMPLER)
    action()
    pg.wait_for_timeout(wait)
    rows = pg.evaluate("() => window.__s")
    pg.evaluate("() => window.__stop()")
    steps = [rows[i]["y"] - rows[i-1]["y"] for i in range(1, len(rows))]
    print(f"{label}: {len(rows)} 帧, 末位 {rows[-1]['y'] if rows else '-'}, 最大单步 {max(steps) if steps else 0}, 前6 {rows[:6]}")
    return rows

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(BASE + "/", wait_until="domcontentloaded")
    pg.wait_for_timeout(2500)
    pg.mouse.move(700, 500)

    # 1) 触控板式小 delta：10 次 20px，间隔 16ms
    def trackpad():
        for _ in range(10):
            pg.mouse.wheel(0, 20)
            pg.wait_for_timeout(16)
    sample(pg, "trackpad 10x20", trackpad)

    # 2) 快速连滚后终点是否等于累计距离
    pg.evaluate("() => window.scrollTo(0, 0)")
    pg.wait_for_timeout(400)
    def burst():
        for _ in range(6):
            pg.mouse.wheel(0, 100)
            pg.wait_for_timeout(16)
    rows = sample(pg, "burst 6x100", burst, wait=900)
    print("  累计 6*100*1.15 =", round(6*100*1.15))

    # 3) 路由切换：滚动到 800 → 点卡片进详情，页面应停在 0 且不回弹
    pg.evaluate("() => window.scrollTo(0, 800)")
    pg.wait_for_timeout(500)
    before = pg.evaluate("() => window.scrollY")
    pg.mouse.click(700, 420)
    pg.wait_for_timeout(1200)
    after = pg.evaluate("() => ({ y: window.scrollY, path: location.pathname })")
    pg.wait_for_timeout(800)
    after2 = pg.evaluate("() => window.scrollY")
    print(f"route: before={before} after={after} settled={after2}")

    # 4) 模态锁：设置页清 key 确认框打开时滚轮不动页面
    pg.goto(BASE + "/market", wait_until="domcontentloaded")
    pg.wait_for_timeout(2200)
    pg.evaluate("() => window.scrollTo(0, 120)")
    pg.wait_for_timeout(400)
    # 打开第一个「卸载」确认框
    pg.evaluate("""() => {
      const btns = [...document.querySelectorAll('button')].filter(b => b.textContent.trim() === '卸载');
      btns[0] && btns[0].click();
    }""")
    pg.wait_for_timeout(400)
    dialog = pg.evaluate("() => Boolean(document.querySelector('[role=dialog]'))")
    y0 = pg.evaluate("() => window.scrollY")
    pg.mouse.wheel(0, 600)
    pg.wait_for_timeout(500)
    y1 = pg.evaluate("() => window.scrollY")
    print(f"modal: dialog={dialog} y {y0} -> {y1}")
    b.close()
