# -*- coding: utf-8 -*-
"""TabRail 连续段胶囊：相邻合并 / 断开分条 / 新段扩散。"""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for name in ("TMP", "TEMP", "TMPDIR"):
    os.environ[name] = str(ROOT / ".onefeed" / "tmp")
(ROOT / ".onefeed" / "tmp").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:8791"
DESIGN = ROOT / "design"


def rail(page):
    return page.locator('[role="group"][aria-label*="平台"]')


def state(page):
    return page.evaluate(
        """() => {
        const btns = [...document.querySelectorAll('[role="group"][aria-label*="平台"] [data-value]')];
        const runs = new Map();
        for (const b of btns) {
          const p = b.parentElement;
          if (!p.classList.contains('bg-solid')) continue;
          if (!runs.has(p)) runs.set(p, { ids: [], width: Math.round(p.getBoundingClientRect().width), x: Math.round(p.getBoundingClientRect().x), radius: getComputedStyle(p).borderRadius });
          runs.get(p).ids.push(b.dataset.value);
        }
        return {
          pressed: btns.filter(b => b.getAttribute('aria-pressed') === 'true').map(b => b.dataset.value),
          runs: [...runs.values()],
          railWidth: Math.round(document.querySelector('[role="group"][aria-label*="平台"]').parentElement.getBoundingClientRect().width),
        };
      }"""
    )


def click(page, value, mods=None):
    page.locator('[data-value="%s"]' % value).click(modifiers=mods or [])


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))
    page.on("console", lambda m: errors.append("console: %s" % m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_selector('[data-value="all"]')
    page.wait_for_timeout(400)
    print("初始:", json.dumps(state(page), ensure_ascii=False))

    click(page, "douyin")
    page.wait_for_timeout(450)
    print("单选抖音:", json.dumps(state(page), ensure_ascii=False))

    click(page, "juejin", ["Control"])
    page.wait_for_timeout(60)
    rail(page).locator("xpath=..").screenshot(path=str(DESIGN / "tabrail-run-growing.png"))
    page.wait_for_timeout(420)
    print("Ctrl+掘金(相邻):", json.dumps(state(page), ensure_ascii=False))
    rail(page).locator("xpath=..").screenshot(path=str(DESIGN / "tabrail-run-merged.png"))

    click(page, "v2ex", ["Control"])
    page.wait_for_timeout(500)
    print("Ctrl+V2EX(仍相邻):", json.dumps(state(page), ensure_ascii=False))

    click(page, "bilibili")
    page.wait_for_timeout(450)
    click(page, "juejin", ["Control"])
    page.wait_for_timeout(60)
    rail(page).locator("xpath=..").screenshot(path=str(DESIGN / "tabrail-run-split-growing.png"))
    page.wait_for_timeout(450)
    print("B站 + 掘金(不相邻):", json.dumps(state(page), ensure_ascii=False))
    rail(page).locator("xpath=..").screenshot(path=str(DESIGN / "tabrail-run-split.png"))

    click(page, "bilibili")
    page.wait_for_timeout(300)
    click(page, "v2ex", ["Shift"])
    page.wait_for_timeout(500)
    print("Shift 选段 B站→V2EX:", json.dumps(state(page), ensure_ascii=False))
    rail(page).locator("xpath=..").screenshot(path=str(DESIGN / "tabrail-run-shift.png"))

    print("errors:", errors)
    browser.close()
