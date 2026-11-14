import os, sys
root = r"E:\Documents\deepseek-harness\default-workspace\onefeed"
tmp = os.path.join(root, ".onefeed", "tmp")
os.makedirs(tmp, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = tmp
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8787"
out = os.path.join(root, "design")
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
    page.goto(BASE + "/", wait_until="networkidle")
    page.wait_for_selector("article", timeout=20000)
    page.wait_for_timeout(1200)
    # 滚到知乎榜单出现
    for _ in range(12):
        if page.locator("article:has-text('知乎')").count():
            break
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(400)
    page.wait_for_timeout(800)
    page.screenshot(path=os.path.join(out, "app-feed-list.png"))
    # 一句话筛选
    page.goto(BASE + "/", wait_until="networkidle")
    page.fill("input", "只看今天 B 站的 AI")
    page.click("text=筛选")
    page.wait_for_timeout(1500)
    page.screenshot(path=os.path.join(out, "app-filter.png"))
    print("parsed:", page.locator("text=理解").count())
    browser.close()
print("done")
