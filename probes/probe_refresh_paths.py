"""刷新按钮的两条路径：全部冷却时立刻给「仍要抓」；有平台可抓时说开始刷新。"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8799"
OUT = ROOT / "probes" / "out"
OUT.mkdir(parents=True, exist_ok=True)


def toast_text(page) -> str:
    return page.evaluate(
        "() => { const n = document.querySelector('[role=status]'); return n ? n.innerText : '' }"
    )


def main() -> int:
    report: dict[str, object] = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.wait_for_selector("article", timeout=20000)
        page.wait_for_timeout(600)

        page.get_by_role("button", name="刷新").click()
        page.wait_for_timeout(900)
        report["toast_right_after_click"] = toast_text(page)
        report["still_fetch"] = page.get_by_role("button", name="仍要抓").count()
        page.screenshot(path=str(OUT / "refresh-cooldown.png"))

        if report["still_fetch"]:
            page.get_by_role("button", name="仍要抓").click()
            page.wait_for_timeout(900)
            report["toast_after_force"] = toast_text(page)
            for _ in range(40):
                time.sleep(5)
                still = page.evaluate("() => !!document.querySelector('header .animate-spin')")
                if not still:
                    break

        page.goto(BASE + "/settings", wait_until="domcontentloaded")
        page.wait_for_timeout(1000)
        page.get_by_role("button", name="采集与排序").first.click()
        page.wait_for_timeout(600)
        box = page.locator("input[aria-label='V2EX 抓取间隔（分钟）']")
        report["interval_before"] = box.input_value()
        box.fill("6")
        page.get_by_role("button", name="保存").first.click()
        page.wait_for_timeout(1500)
        report["save_toast"] = toast_text(page)
        page.screenshot(path=str(OUT / "settings-intervals.png"))
        box2 = page.locator("input[aria-label='V2EX 抓取间隔（分钟）']")
        box2.fill("5")
        page.get_by_role("button", name="保存").first.click()
        page.wait_for_timeout(1200)
        report["interval_restored_toast"] = toast_text(page)
        browser.close()

    text = json.dumps(report, ensure_ascii=False, indent=2)
    (OUT / "refresh-paths.json").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
