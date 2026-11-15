"""UI 截图：信息流 / 详情抽屉（B 站评论）/ 设置页。"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8788")
OUT = ROOT / "design"
OUT.mkdir(exist_ok=True)
sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(2200)
        page.screenshot(path=str(OUT / "ui-feed.png"))
        print("feed ok", page.locator("article").count(), "cards")

        target = page.locator("article", has_text="炉石bug").first
        if target.count() == 0:
            target = page.locator("article").first
        target.scroll_into_view_if_needed()
        target.click()
        page.wait_for_timeout(9000)
        page.screenshot(path=str(OUT / "ui-drawer.png"))
        print("drawer ok")

        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        page.goto(BASE + "/settings", wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path=str(OUT / "ui-settings.png"))
        page.screenshot(path=str(OUT / "ui-settings-full.png"), full_page=True)
        print("settings ok")
        browser.close()


if __name__ == "__main__":
    main()
