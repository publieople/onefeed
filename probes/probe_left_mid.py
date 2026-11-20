"""左栏补间中途截图：看交叉淡入是否有重影。"""
from __future__ import annotations

import os

from playwright.sync_api import sync_playwright

URL = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799/")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding"])
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("[data-shell-left]")
        page.wait_for_timeout(1000)
        clip = {"x": 0, "y": 57, "width": 300, "height": 700}

        # 收起中途
        page.keyboard.press("[")
        for ms, name in ((70, "c070"), (140, "c140")):
            page.wait_for_timeout(ms if name == "c070" else 70)
            page.screenshot(path=f"docs/images/2026-11-20-left-{name}.png", clip=clip)
        page.wait_for_timeout(600)

        # 展开中途
        page.keyboard.press("[")
        page.wait_for_timeout(900)
        page.keyboard.press("[")
        for ms, name in ((70, "e070"), (140, "e140")):
            page.wait_for_timeout(ms if name == "e070" else 70)
            page.screenshot(path=f"docs/images/2026-11-20-left-{name}.png", clip=clip)
        browser.close()


if __name__ == "__main__":
    main()
