"""减少动态效果下左栏应当是跳变，不是补间。"""
from __future__ import annotations

import json
import os

from playwright.sync_api import sync_playwright

URL = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799/")

SAMPLER = """
() => {
  const col = document.querySelector('[data-shell-left]');
  const s = { frames: [], on: true };
  window.__s = s;
  let prev = performance.now();
  const tick = (t) => {
    s.frames.push({ dt: Math.round(t - prev), w: +col.getBoundingClientRect().width.toFixed(1) });
    prev = t;
    if (s.on) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
"""
STOP = "() => { window.__s.on = false; return window.__s; }"


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.emulate_media(reduced_motion="reduce")
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("[data-shell-left]")
        page.wait_for_timeout(900)
        print("reduce flag:", page.evaluate("() => matchMedia('(prefers-reduced-motion: reduce)').matches"))
        print("start width:", page.evaluate("() => Math.round(document.querySelector('[data-shell-left]').getBoundingClientRect().width)"))
        page.evaluate(SAMPLER)
        page.keyboard.press("[")
        page.wait_for_timeout(600)
        data = page.evaluate(STOP)
        print(json.dumps([f["w"] for f in data["frames"][:10]], ensure_ascii=False))
        print("dts", [f["dt"] for f in data["frames"][:10]])
        browser.close()


if __name__ == "__main__":
    main()
