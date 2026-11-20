"""左栏收栏连测：看那次长任务是冷的第一次，还是每次都有。"""
from __future__ import annotations

import json
import os

from playwright.sync_api import sync_playwright

URL = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799/")

SAMPLER = """
() => {
  const col = document.querySelector('[data-shell-left]');
  const s = { frames: [], long: [], on: true };
  window.__s = s;
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) s.long.push(Math.round(e.duration));
    }).observe({ type: 'longtask', buffered: false });
  } catch (err) {}
  let prev = performance.now();
  const tick = (t) => {
    s.frames.push({ t: Math.round(t), dt: Math.round(t - prev), w: +col.getBoundingClientRect().width.toFixed(1) });
    prev = t;
    if (s.on) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
"""
STOP = "() => { window.__s.on = false; return window.__s; }"


def main() -> None:
    rounds = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("[data-shell-left]")
        page.wait_for_timeout(1200)
        for i in range(3):
            page.evaluate(SAMPLER)
            page.keyboard.press("[")
            page.wait_for_timeout(800)
            data = page.evaluate(STOP)
            dts = [f["dt"] for f in data["frames"][1:]]
            rounds.append({
                "round": i + 1,
                "long": data["long"],
                "dt": dts[:12],
                "widths": [f["w"] for f in data["frames"][:10]],
            })
            page.keyboard.press("[")
            page.wait_for_timeout(900)
        # 收栏时把卡片藏起来对照：看长任务是不是卡片重排造成的
        page.evaluate("() => { const g = document.querySelector('[data-vt-grid]') || document.querySelector('main .grid'); if (g) g.style.display='none'; }")
        page.wait_for_timeout(300)
        page.evaluate(SAMPLER)
        page.keyboard.press("[")
        page.wait_for_timeout(800)
        nodgrid = page.evaluate(STOP)
        rounds.append({"round": "no-cards", "long": nodgrid["long"], "dt": [f["dt"] for f in nodgrid["frames"][1:12]], "widths": [f["w"] for f in nodgrid["frames"][:10]]})
        browser.close()
    print(json.dumps(rounds, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
