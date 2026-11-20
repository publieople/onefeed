"""窗口缩放仍要重算列数（稳定 ≠ 冻死），并复验窄屏下侧栏开合同样不翻列。"""
from __future__ import annotations

import json
import os

from playwright.sync_api import sync_playwright

URL = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799/")
SHOT = """() => {
  const grid = document.querySelector('[data-vt-grid]') || document.querySelector('main .grid');
  if (!grid) return null;
  const cs = getComputedStyle(grid).gridTemplateColumns;
  const card = grid.firstElementChild;
  const l = document.querySelector('[data-shell-left]');
  return {
    cols: cs.split(' ').filter(Boolean).length,
    card: card ? +card.getBoundingClientRect().width.toFixed(1) : 0,
    left: l ? +l.getBoundingClientRect().width.toFixed(1) : 0,
  };
}"""
SAMPLER = """
() => {
  const grid = document.querySelector('[data-vt-grid]') || document.querySelector('main .grid');
  const s = { cols: new Set(), card: [], on: true };
  window.__s = s;
  const tick = () => {
    const cs = getComputedStyle(grid).gridTemplateColumns;
    s.cols.add(cs.split(' ').filter(Boolean).length);
    const card = grid.firstElementChild;
    if (card) s.card.push(+card.getBoundingClientRect().width.toFixed(1));
    if (s.on) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
"""
STOP = "() => { window.__s.on = false; return { cols: [...window.__s.cols], card: window.__s.card }; }"


def main() -> None:
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("[data-vt-grid], main .grid")
        page.wait_for_timeout(1200)
        out["1440"] = page.evaluate(SHOT)

        for w in (1100, 900, 1600):
            page.set_viewport_size({"width": w, "height": 900})
            page.wait_for_timeout(700)
            out[str(w)] = page.evaluate(SHOT)

        page.set_viewport_size({"width": 1100, "height": 900})
        page.wait_for_timeout(600)
        before = page.evaluate(SHOT)
        page.evaluate(SAMPLER)
        page.keyboard.press("[")
        page.wait_for_timeout(900)
        data = page.evaluate(STOP)
        after = page.evaluate(SHOT)
        out["narrow_left_expand"] = {
            "before": before,
            "after": after,
            "cols_seen": data["cols"],
            "card_w": [min(data["card"]), max(data["card"])] if data["card"] else None,
            "ok": len(data["cols"]) == 1 and before["cols"] == after["cols"],
        }
        page.screenshot(path=".onefeed/tmp/shot-grid-stable-narrow.png", clip={"x": 0, "y": 0, "width": 1100, "height": 520})
        browser.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
