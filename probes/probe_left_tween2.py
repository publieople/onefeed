"""左栏宽度补间：轻量帧采样 + 右栏对照。

采样器只读列宽（不碰 getComputedStyle，避免每帧强制样式重算），
长任务由 PerformanceObserver 单独记。
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

RAIL_SAMPLER = SAMPLER.replace(
    "document.querySelector('[data-shell-left]')",
    "document.querySelector('[data-rail=\"slot\"]')",
)

STOP = "() => { window.__s.on = false; return window.__s; }"


def summarize(label: str, data: dict) -> dict:
    frames = data["frames"]
    widths = [f["w"] for f in frames]
    distinct = sorted({w for w in widths})
    dts = [f["dt"] for f in frames[2:]]
    moving = [f for f in frames if 0 < f["w"] < max(widths)]
    out = {
        "frames": len(frames),
        "distinct": len(distinct),
        "max_step": max((abs(widths[i + 1] - widths[i]) for i in range(len(widths) - 1)), default=0),
        "dt_max": max(dts) if dts else 0,
        "dt_p95": round(statistics.quantiles(dts, n=20)[-1]) if len(dts) > 20 else None,
        "long": data["long"],
    }
    print(f"\n--- {label} ---")
    print(json.dumps(out, ensure_ascii=False))
    print("widths", widths[:16])
    return out


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("[data-shell-left]")
        page.wait_for_timeout(1200)

        page.evaluate(SAMPLER)
        page.keyboard.press("[")
        page.wait_for_timeout(900)
        collapse = page.evaluate(STOP)

        page.evaluate(SAMPLER)
        page.keyboard.press("[")
        page.wait_for_timeout(900)
        expand = page.evaluate(STOP)

        page.evaluate(RAIL_SAMPLER)
        page.keyboard.press("]")
        page.wait_for_timeout(900)
        rail_open = page.evaluate(STOP)

        page.evaluate(RAIL_SAMPLER)
        page.keyboard.press("]")
        page.wait_for_timeout(900)
        rail_close = page.evaluate(STOP)

        browser.close()

    res = {
        "collapse": summarize("left collapse 240 -> 64", collapse),
        "expand": summarize("left expand 64 -> 240", expand),
        "rail_open": summarize("right open 0 -> 320", rail_open),
        "rail_close": summarize("right close 320 -> 0", rail_close),
    }
    with open(".onefeed/tmp/left-tween2.json", "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
