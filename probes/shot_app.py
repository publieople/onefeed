import os, sys, time
root = r"E:\Documents\deepseek-harness\default-workspace\onefeed"
tmp = os.path.join(root, ".onefeed", "tmp")
os.makedirs(tmp, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = tmp
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8787"
out = os.path.join(root, "design")
os.makedirs(out, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
    page.goto(BASE + "/", wait_until="networkidle")
    page.wait_for_selector("article", timeout=20000)
    page.wait_for_timeout(1800)
    page.screenshot(path=os.path.join(out, "app-feed.png"))
    page.locator("article").first.click()
    page.wait_for_timeout(1400)
    page.screenshot(path=os.path.join(out, "app-drawer.png"))
    page.keyboard.press("Escape")
    page.goto(BASE + "/market", wait_until="networkidle")
    page.wait_for_timeout(1200)
    page.screenshot(path=os.path.join(out, "app-market.png"))
    page.goto(BASE + "/settings", wait_until="networkidle")
    page.wait_for_timeout(1200)
    page.screenshot(path=os.path.join(out, "app-settings.png"))
    print("title:", page.title())
    browser.close()
print("done")
