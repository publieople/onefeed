"""给三种胶囊动效各拍一张中间帧：平移途中、相邻长出去的中途、从点击中心扩散的起手。"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(TMP)

from playwright.sync_api import sync_playwright  # noqa: E402

SHOTS = ROOT / "design"
URL = "http://127.0.0.1:8791/"
CLIP = {"x": 140, "y": 108, "width": 760, "height": 70}


def clip_rail(page, name):
    page.screenshot(path=str(SHOTS / name), clip=CLIP)


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    page = ctx.new_page()
    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector("button[data-value]")
    page.wait_for_timeout(700)

    # 1) 单选平移：全部 → 抖音，抓 110ms 的中途
    page.locator('button[data-value="douyin"]').click()
    page.wait_for_timeout(110)
    clip_rail(page, "tabrail-mode-slide.png")
    page.wait_for_timeout(700)

    # 2) 相邻扩散：Ctrl 加掘金，抓从抖音那段长出去的中途
    page.locator('button[data-value="juejin"]').click(modifiers=["Control"])
    page.wait_for_timeout(130)
    clip_rail(page, "tabrail-mode-adjacent.png")
    page.wait_for_timeout(700)

    # 3) 中心扩散：Ctrl 加知乎，趁窄条还在、淡影还没散时抓
    page.locator('button[data-value="zhihu"]').click(modifiers=["Control"])
    page.wait_for_timeout(75)
    clip_rail(page, "tabrail-mode-center.png")
    page.wait_for_timeout(700)

    ctx.close()
    browser.close()
print("OK")
