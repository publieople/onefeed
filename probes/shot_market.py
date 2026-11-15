"""插件市场截图：更新提示 → 点「更新」→ 更新完成。"""
import json
import os
import sys
import urllib.request
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


def updates() -> dict:
    with urllib.request.urlopen(BASE + "/api/market/updates", timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    print("pending before:", updates())
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900},
                                device_scale_factor=1.5)
        page.goto(BASE + "/market", wait_until="networkidle")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(OUT / "ui-market.png"))
        print("market ok, buttons:", page.get_by_role("button", name="更新").count())

        btn = page.get_by_role("button", name="更新", exact=True).first
        if btn.count():
            btn.click()
            page.wait_for_timeout(6000)
            page.screenshot(path=str(OUT / "ui-market-after.png"))
            print("clicked update")
        browser.close()
    print("pending after:", updates())


if __name__ == "__main__":
    main()
