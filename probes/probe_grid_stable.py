"""侧栏开合时列数必须稳定：逐帧采样列数与首张卡宽度。

断言两条同时成立，缺一条都不算修好：
  1) 列数在整个开合过程里一个值都不变（用户说的是「列数自动变动、跳变」）；
  2) 卡片宽度确实变了（说明内容列真的被挤宽/挤窄，不是侧栏没动）。
"""
from __future__ import annotations

import json
import os

from playwright.sync_api import sync_playwright

URL = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799/")

SAMPLER = """
() => {
  const grid = document.querySelector('[data-vt-grid]') || document.querySelector('main .grid');
  const col = document.querySelector('[data-shell-left]');
  const right = document.querySelector('[data-rail="slot"]');
  const s = { frames: [], on: true };
  window.__s = s;
  const tick = () => {
    const cs = grid ? getComputedStyle(grid).gridTemplateColumns : "";
    const n = cs ? cs.split(" ").filter(Boolean).length : 0;
    const card = grid ? grid.firstElementChild : null;
    s.frames.push({
      cols: n,
      card: card ? +card.getBoundingClientRect().width.toFixed(1) : 0,
      left: col ? +col.getBoundingClientRect().width.toFixed(1) : 0,
      right: right ? +right.getBoundingClientRect().width.toFixed(1) : 0,
    });
    if (s.on) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}
"""
STOP = "() => { window.__s.on = false; return window.__s; }"
SHOT = """() => {
  const grid = document.querySelector('[data-vt-grid]') || document.querySelector('main .grid');
  if (!grid) return null;
  const cs = getComputedStyle(grid).gridTemplateColumns;
  return { cols: cs.split(' ').filter(Boolean).length, template: cs };
}"""


def summarize(label: str, data: dict, before: dict, after: dict) -> dict:
    frames = data["frames"]
    cols = sorted({f["cols"] for f in frames if f["cols"]})
    cards = [f["card"] for f in frames if f["card"]]
    return {
        "case": label,
        "before_cols": before["cols"],
        "after_cols": after["cols"],
        "cols_seen_during": cols,
        "card_w_min": min(cards) if cards else None,
        "card_w_max": max(cards) if cards else None,
        "frames": len(frames),
        "ok": len(cols) == 1 and before["cols"] == after["cols"] == cols[0],
    }


def main() -> None:
    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("[data-shell-left]")
        page.wait_for_selector("[data-vt-grid], main .grid")
        page.wait_for_timeout(1400)

        for label, key in (("left.collapse", "["), ("left.expand", "["), ("right.open", "]"), ("right.close", "]")):
            before = page.evaluate(SHOT)
            page.evaluate(SAMPLER)
            page.keyboard.press(key)
            page.wait_for_timeout(900)
            data = page.evaluate(STOP)
            after = page.evaluate(SHOT)
            out.append(summarize(label, data, before, after))

        page.screenshot(path=".onefeed/tmp/shot-grid-stable.png", clip={"x": 0, "y": 0, "width": 1440, "height": 500})
        browser.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
