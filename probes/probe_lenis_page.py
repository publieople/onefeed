import json
from playwright.sync_api import sync_playwright

SAMP = r"""
() => {
  window.__s = []; window.__w = null; window.__on = true;
  const rec = () => {
    if (!window.__on) return;
    const p = Math.round(window.scrollY);
    const box = document.querySelector('[data-smooth-scroll]');
    const side = box ? Math.round(box.scrollTop) : -1;
    const last = window.__s[window.__s.length - 1];
    if (!last || last.p !== p || last.side !== side) {
      window.__s.push({ t: Math.round(performance.now()), p, side });
    }
  };
  document.addEventListener('wheel', () => { if (window.__w === null) window.__w = Math.round(performance.now()); }, { capture: true, passive: true });
  document.addEventListener('scroll', rec, { capture: true, passive: true });
  window.__raf = [];
  let prev = performance.now();
  const loop = (t) => { window.__raf.push(Math.round(t - prev)); prev = t; if (window.__on) requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
  window.__stop = () => { window.__on = false; };
}
"""

def report(label, pg):
    s = pg.evaluate("() => window.__s")
    w = pg.evaluate("() => window.__w")
    raf = pg.evaluate("() => window.__raf")
    pg.evaluate("() => window.__stop()")
    key = "side" if "sidebar" in label or "->" in label else "p"
    if not s:
        print(label, "NO SAMPLE"); return
    base = s[0][key]
    movers = [x for x in s if x[key] != base]
    big = max(raf) if raf else 0
    if not movers:
        print(f"{label}: 没动 (wheel {w}) raf max {big}ms"); return
    steps, prev = [], base
    for x in movers:
        steps.append(x[key] - prev); prev = x[key]
    print(f"{label}: 首动 {movers[0]['t'] - (w or movers[0]['t'])}ms / {len(movers)} 次变化 / 用时 {movers[-1]['t']-movers[0]['t']}ms / 位移 {movers[-1][key]-base}px / 最大单步 {max(steps)}px / raf 最大间隔 {big}ms")

with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome", headless=True)

    def fresh():
        pg = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        pg.goto("http://127.0.0.1:8799/", wait_until="domcontentloaded")
        pg.wait_for_timeout(2600)
        pg.evaluate(SAMP)
        return pg

    pg = fresh(); pg.mouse.move(700, 300); pg.mouse.wheel(0, 100); pg.wait_for_timeout(1400); report("page 1 tick", pg); pg.close()
    pg = fresh(); pg.mouse.move(700, 300)
    for _ in range(3):
        pg.mouse.wheel(0, 100); pg.wait_for_timeout(60)
    pg.wait_for_timeout(1600); report("page 3 ticks", pg); pg.close()
    pg = fresh()
    box = pg.evaluate("() => { const el = document.querySelector('[data-smooth-scroll]'); el.scrollTop = 0; const r = el.getBoundingClientRect(); return {x: r.x + r.width/2, y: r.y + r.height/2}; }")
    pg.mouse.move(box["x"], box["y"]); pg.mouse.wheel(0, 100); pg.wait_for_timeout(1400); report("sidebar 1 tick", pg); pg.close()
    pg = fresh()
    box = pg.evaluate("() => { const el = document.querySelector('[data-smooth-scroll]'); el.scrollTop = el.scrollHeight; const r = el.getBoundingClientRect(); return {x: r.x + r.width/2, y: r.y + r.height/2}; }")
    pg.wait_for_timeout(500); pg.mouse.move(box["x"], box["y"]); pg.mouse.wheel(0, 400); pg.wait_for_timeout(1500); report("sidebar bottom -> page", pg); pg.close()

    # 模态锁：点 AI 输入框打开面板不算模态；用快捷键 ? 打开帮助层更稳
    pg = fresh()
    pg.keyboard.press("?")
    pg.wait_for_timeout(500)
    pg.mouse.move(700, 300); pg.mouse.wheel(0, 400); pg.wait_for_timeout(900)
    print("modal open scrollY:", pg.evaluate("() => Math.round(window.scrollY)"))
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    pg.mouse.wheel(0, 200); pg.wait_for_timeout(1200)
    print("after esc scrollY:", pg.evaluate("() => Math.round(window.scrollY)"))
    pg.close()
    b.close()
