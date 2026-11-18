import os
TMP = os.path.join(r"E:\Documents\deepseek-harness\default-workspace\onefeed", ".onefeed", "tmp")
os.makedirs(TMP, exist_ok=True)
for n in ("TMP", "TEMP", "TMPDIR"):
    os.environ[n] = TMP
from playwright.sync_api import sync_playwright

OUT = r"E:\Documents\deepseek-harness\default-workspace\onefeed\design"
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    page.goto("http://127.0.0.1:8791/", wait_until="networkidle")
    page.wait_for_selector("[data-value]")
    page.click('[data-value="douyin"]')
    page.click('[data-value="zhihu"]', modifiers=["Shift"])
    page.wait_for_timeout(900)
    box = page.locator('[role=group][aria-label^="按平台筛选"]').first.bounding_box()
    print("box", box)
    clip = {"x": box["x"] - 14, "y": box["y"] - 10, "width": box["width"] + 28, "height": box["height"] + 20}
    page.screenshot(path=os.path.join(OUT, "tabrail-multi.png"), clip=clip, scale="device")
    # 暗色同一状态
    page.click('button[aria-label="切换到暗色"]')
    page.wait_for_timeout(600)
    page.screenshot(path=os.path.join(OUT, "tabrail-multi-dark.png"), clip=clip, scale="device")
    b.close()
print("done")
