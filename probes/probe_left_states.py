"""左栏补间的功能复核：截图、层可见性、浮层跟随、reduce。"""
from __future__ import annotations

import json
import os

from playwright.sync_api import sync_playwright

URL = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799/")

REPORT = """
() => {
  const col = document.querySelector('[data-shell-left]');
  const full = document.querySelector('[data-shell-layer="full"]');
  const rail = document.querySelector('[data-shell-layer="rail"]');
  const pill = document.querySelector('[data-agent-launcher]');
  const cs = (el) => getComputedStyle(el);
  return {
    colW: Math.round(col.getBoundingClientRect().width),
    colState: col.getAttribute('data-shell-left'),
    full: { opacity: +cs(full).opacity, visibility: cs(full).visibility, w: Math.round(full.getBoundingClientRect().width) },
    rail: { opacity: +cs(rail).opacity, visibility: cs(rail).visibility, w: Math.round(rail.getBoundingClientRect().width) },
    launcherLeft: pill ? Math.round(pill.getBoundingClientRect().left) : null,
    vars: {
      left: getComputedStyle(document.documentElement).getPropertyValue('--shell-left-w').trim(),
      right: getComputedStyle(document.documentElement).getPropertyValue('--shell-right-w').trim(),
    },
    // 折叠态下图标轨里的按钮必须点得到
    railHit: (() => {
      const b = rail.querySelector('button');
      if (!b) return null;
      const r = b.getBoundingClientRect();
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return { tag: hit && hit.tagName, inside: !!(hit && rail.contains(hit)) };
    })(),
    // 隐藏层里的可聚焦元素不能进 Tab 序列（visibility:hidden 天然做到）
    fullFocusable: Array.from(full.querySelectorAll('button,a[href],input')).filter((el) => el.offsetParent !== null).length,
  };
}
"""


def main() -> None:
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("[data-shell-left]")
        page.wait_for_timeout(1000)
        out["expanded"] = page.evaluate(REPORT)
        page.screenshot(path="docs/images/2026-11-20-left-expanded.png", clip={"x": 0, "y": 0, "width": 520, "height": 900})

        page.keyboard.press("[")
        page.wait_for_timeout(900)
        out["collapsed"] = page.evaluate(REPORT)
        page.screenshot(path="docs/images/2026-11-20-left-collapsed.png", clip={"x": 0, "y": 0, "width": 520, "height": 900})

        # 收起状态下点图标轨的新对话按钮，确认事件没被满宽的展开层挡住
        page.keyboard.press("[")
        page.wait_for_timeout(900)

        # reduce：应当一步到位
        page.emulate_media(reduced_motion="reduce")
        page.keyboard.press("[")
        page.wait_for_timeout(60)
        out["reduce_60ms"] = page.evaluate("() => Math.round(document.querySelector('[data-shell-left]').getBoundingClientRect().width)")
        page.wait_for_timeout(500)
        out["reduce_560ms"] = page.evaluate("() => Math.round(document.querySelector('[data-shell-left]').getBoundingClientRect().width)")

        browser.close()
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
