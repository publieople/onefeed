"""左栏宽度补间的帧采样：逐帧记录列宽、两层透明度与长任务。

用法：.venv\\Scripts\\python.exe probes/probe_left_tween.py
"""
from __future__ import annotations

import json
import os
import statistics

from playwright.sync_api import sync_playwright

URL = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799/")

SAMPLER = """
() => {
  const col = document.querySelector('[data-shell-left]');
  const full = document.querySelector('[data-shell-layer="full"]');
  const rail = document.querySelector('[data-shell-layer="rail"]');
  const s = { frames: [], long: [], on: true };
  window.__s = s;
  try {
    new PerformanceObserver((l) => {
      for (const e of l.getEntries()) s.long.push(Math.round(e.duration));
    }).observe({ type: 'longtask', buffered: false });
  } catch (err) {}
  let prev = performance.now();
  const tick = (t) => {
    const w = col.getBoundingClientRect().width;
    s.frames.push({
      t: Math.round(t),
      dt: Math.round(t - prev),
      w: +w.toFixed(1),
      full: +getComputedStyle(full).opacity,
      rail: +getComputedStyle(rail).opacity,
    });
    prev = t;
    if (s.on) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
"""

STOP = "() => { window.__s.on = false; return window.__s; }"


def summarize(label: str, data: dict) -> None:
    frames = data["frames"]
    widths = [f["w"] for f in frames]
    steps = [round(widths[i + 1] - widths[i], 1) for i in range(len(widths) - 1)]
    distinct = sorted({w for w in widths})
    dts = [f["dt"] for f in frames[2:]]
    print(f"\n--- {label} ---")
    print("frames", len(frames), "distinct widths", len(distinct))
    print("widths", widths[:14], "..." if len(widths) > 14 else "")
    print("distinct", distinct[:16], "..." if len(distinct) > 16 else "")
    print("transition window ms", frames[0]["t"], "->", next((f["t"] for f in frames if f["w"] == distinct[-1]), frames[-1]["t"]))
    print("max step px", max(abs(s) for s in steps) if steps else 0)
    print("dt ms: max", max(dts) if dts else 0, "p95", round(statistics.quantiles(dts, n=20)[-1]) if len(dts) > 20 else "n/a")
    print("long tasks", data["long"], "total", sum(data["long"]))
    print("opacity full", [f["full"] for f in frames[:8]], "rail", [f["rail"] for f in frames[:8]])


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("[data-shell-left]")
        page.wait_for_timeout(900)

        page.evaluate(SAMPLER)
        page.keyboard.press("[")
        page.wait_for_timeout(900)
        collapse = page.evaluate(STOP)

        page.wait_for_timeout(400)
        page.evaluate(SAMPLER)
        page.keyboard.press("[")
        page.wait_for_timeout(900)
        expand = page.evaluate(STOP)

        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(300)
        page.screenshot(path="docs/images/2026-11-20-left-tween.png")
        browser.close()

    summarize("collapse 240 -> 64", collapse)
    summarize("expand 64 -> 240", expand)
    with open(".onefeed/tmp/left-tween.json", "w", encoding="utf-8") as fh:
        json.dump({"collapse": collapse, "expand": expand}, fh, ensure_ascii=False)


if __name__ == "__main__":
    main()
