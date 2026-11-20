"""Lenis 侧栏滚动 + 右栏宽度补间实测（2026-11-20）。

采样必须在页面里做：从 Python 侧 evaluate 往返一次 >200ms，
320ms 的补间采到的全是终态，看起来像「瞬间跳」。
"""
from __future__ import annotations

import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
SHOTS = TMP

INIT = r"""
() => {
  window.__w = {};
  window.__watch = (key, expr) => {
    const fn = new Function("return (" + expr + ")");
    const rows = [], durs = [];
    let running = true, last = performance.now();
    const tick = () => {
      if (!running) return;
      const now = performance.now();
      let v = null;
      try { v = fn(); } catch (e) {}
      rows.push([+now.toFixed(1), v === null ? null : +Number(v).toFixed(1)]);
      durs.push(+(now - last).toFixed(1));
      last = now;
      requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
    window.__w[key] = {rows, durs, stop: () => { running = false; }};
    return true;
  };
  window.__reset = (key) => { const b = window.__w[key]; b.rows.length = 0; b.durs.length = 0; };
  window.__take = (key) => { const b = window.__w[key]; b.stop(); return {rows: b.rows, durs: b.durs}; };
}
"""

RAIL_W = ("(() => { const r = document.querySelector('[data-rail=\"slot\"]');"
          " return r ? r.parentElement.getBoundingClientRect().width : 0; })()")
MAIN_W = "document.querySelector('main').getBoundingClientRect().width"


def summary(rows, durs):
    vals = [r[1] for r in rows if r[1] is not None]
    steps = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
    span = rows[-1][0] - rows[0][0] if len(rows) > 1 else 0
    return {
        "frames": len(rows),
        "span_ms": round(span),
        "from": vals[0] if vals else None,
        "to": vals[-1] if vals else None,
        "distinct": len(set(vals)),
        "max_step": round(max(steps), 1) if steps else 0,
        "max_frame_ms": round(max(durs), 1) if durs else 0,
        "frames_gt_60": sum(1 for d in durs if d > 60),
    }


out: dict = {"base": BASE}
with sync_playwright() as pw:
    browser = pw.chromium.launch(
        channel="chrome",
        headless=True,
        args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding",
              "--disable-backgrounding-occluded-windows", "--window-size=1600,900"],
    )
    page = browser.new_page(viewport={"width": 1600, "height": 900})
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector('[data-smooth-scroll]', timeout=15000)
    page.wait_for_timeout(1200)
    page.evaluate(INIT)
    out["visibility"] = page.evaluate("document.visibilityState")
    out["lenis_class"] = page.evaluate("document.querySelectorAll('.lenis').length")

    side = '[data-smooth-scroll]'
    box = page.evaluate(
        """(sel) => { const el = document.querySelector(sel);
             const r = el.getBoundingClientRect();
             return {x: r.x, y: r.y, w: r.width, h: r.height, top: el.scrollTop,
                     sh: el.scrollHeight, ch: el.clientHeight,
                     overflow: getComputedStyle(el).overflowY, cls: (el.className || '').slice(0, 50)}; }""",
        side,
    )
    out["sidebar_box"] = box

    # ---- 侧栏滚轮：三格连续输入，看是否累积成一次长行程 ----
    page.mouse.move(box["x"] + box["w"] / 2, box["y"] + min(box["h"] - 40, 300))
    page.evaluate("() => window.__watch('side', 'document.querySelector(\"[data-smooth-scroll]\").scrollTop')")
    t0 = time.time()
    for _ in range(3):
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(110)
    page.wait_for_timeout(1100)
    taken = page.evaluate("() => window.__take('side')")
    out["wheel_3x400"] = summary(taken["rows"], taken["durs"])
    out["wheel_3x400"]["wall_ms"] = round((time.time() - t0) * 1000)

    # ---- 对照：页面本体的滚轮不被 Lenis 接管（只接管 [data-smooth-scroll]）----
    page.evaluate("() => window.scrollTo({ top: 0, behavior: 'instant' })")
    page.wait_for_timeout(200)
    page.mouse.move(800, 500)
    page.mouse.wheel(0, 500)
    page.wait_for_timeout(60)
    out["body_wheel_60ms"] = page.evaluate("Math.round(window.scrollY)")
    page.wait_for_timeout(600)
    out["body_wheel_settled"] = page.evaluate("Math.round(window.scrollY)")
    page.evaluate("() => window.scrollTo({ top: 0, behavior: 'instant' })")
    page.wait_for_timeout(200)

    # ---- 右栏宽度补间：打开、再关掉 ----
    page.evaluate("() => { window.__watch('rail', " + json.dumps(RAIL_W) + "); window.__watch('main', " + json.dumps(MAIN_W) + "); }")
    chip = page.evaluate(
        """() => {
          const nodes = [...document.querySelectorAll('button, [role=button]')];
          const hit = nodes.find(n => (n.textContent || '').trim().startsWith('稍后再看'));
          if (!hit) return null;
          const r = hit.getBoundingClientRect();
          return {x: r.x + r.width / 2, y: r.y + r.height / 2, text: hit.textContent.trim().slice(0, 20)};
        }"""
    )
    out["chip"] = chip
    if chip:
        page.mouse.click(chip["x"], chip["y"])
        page.wait_for_timeout(900)
        rail = page.evaluate("() => window.__take('rail')")
        main = page.evaluate("() => window.__take('main')")
        out["rail_open"] = summary(rail["rows"], rail["durs"])
        out["main_open"] = summary(main["rows"], main["durs"])
        page.screenshot(path=str(SHOTS / "shot-rail-open.png"))
        out["rail_open"]["final_present"] = page.evaluate("!!document.querySelector('[data-rail=\"slot\"]')")

        # 关：点右栏自己的「收起右栏」
        close_btn = page.evaluate(
            """() => { const a = document.querySelector('[data-rail=\"slot\"]');
                 const btn = a && [...a.querySelectorAll('button')]
                   .find(b => (b.getAttribute('aria-label') || '').includes('收起'));
                 if (!btn) return null;
                 const r = btn.getBoundingClientRect();
                 return {x: r.x + r.width / 2, y: r.y + r.height / 2}; }"""
        )
        out["close_button"] = bool(close_btn)
        page.evaluate("() => { window.__watch('rail2', " + json.dumps(RAIL_W) + "); window.__watch('main2', " + json.dumps(MAIN_W) + "); }")
        if close_btn:
            page.mouse.click(close_btn["x"], close_btn["y"])
        page.wait_for_timeout(900)
        rail2 = page.evaluate("() => window.__take('rail2')")
        main2 = page.evaluate("() => window.__take('main2')")
        out["rail_close"] = summary(rail2["rows"], rail2["durs"])
        out["main_close"] = summary(main2["rows"], main2["durs"])
        out["rail_after_close"] = page.evaluate(
            """() => ({present: !!document.querySelector('[data-rail="slot"]'),
                       var: getComputedStyle(document.documentElement).getPropertyValue('--shell-right-w')})"""
        )
        page.screenshot(path=str(SHOTS / "shot-rail-closed.png"))

    browser.close()

print(json.dumps(out, ensure_ascii=False, indent=2))
