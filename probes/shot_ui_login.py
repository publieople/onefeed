import os, sys, time
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("PYTHONUTF8", "1")
base = os.path.abspath(".onefeed/tmp")
os.makedirs(base, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = base
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8788/settings"
OUT = os.path.abspath("design")
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5)
    page = ctx.new_page()
    page.goto(URL, wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)

    # 点抖音那一行的「打开登录窗口」
    row = page.locator("li", has_text="抖音").first
    row.scroll_into_view_if_needed()
    row.get_by_role("button", name="打开登录窗口").click()
    page.wait_for_timeout(9000)

    text = page.locator("body").inner_text()
    print("含『窗口开着』:", "窗口开着" in text)
    print("含『登录窗口已打开』:", "登录窗口已打开" in text)
    login_rows = [t for t in text.splitlines() if "窗口" in t]
    print("关于窗口的行:", login_rows[:4])
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(400)
    page.screenshot(path=os.path.join(OUT, "ui-login.png"), full_page=True)

    # 用 API 收尾（等同点「退出」，但窗口还没登录也照样能关）
    page.evaluate("fetch('/api/auth/douyin/logout', {method: 'POST'}).then(r => r.json())")
    page.wait_for_timeout(1200)
    ctx.close()
    browser.close()
print("done")