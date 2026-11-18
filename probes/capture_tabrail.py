import os, sys, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)

from playwright.sync_api import sync_playwright

OUT = ROOT / "design"
OUT.mkdir(exist_ok=True)


def rail_clip(page):
    box = page.locator('[aria-label="按平台筛选"]').locator("xpath=..").bounding_box()
    pad = 10
    return {
        "x": max(0, box["x"] - pad),
        "y": max(0, box["y"] - pad),
        "width": min(1440, box["width"] + pad * 2),
        "height": box["height"] + pad * 2,
    }


def capsule(page):
    el = page.locator('[aria-label="按平台筛选"] span.absolute').first
    if el.count() == 0:
        return None
    return el.bounding_box()


with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=False, args=["--window-size=1440,900"])
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto("http://127.0.0.1:8791/", wait_until="networkidle")
    page.wait_for_selector('button[data-value="all"]', timeout=20000)
    page.wait_for_timeout(1500)

    print("initial capsule:", json.dumps(capsule(page), ensure_ascii=False))
    page.screenshot(path=str(OUT / "tabrail-light-all.png"), clip=rail_clip(page))

    # 切到抖音，抓 90ms 的中间帧
    page.click('button[data-value="douyin"]')
    page.wait_for_timeout(90)
    page.screenshot(path=str(OUT / "tabrail-moving.png"), clip=rail_clip(page))
    print("mid capsule:", json.dumps(capsule(page), ensure_ascii=False))
    page.wait_for_timeout(700)
    page.screenshot(path=str(OUT / "tabrail-light-douyin.png"), clip=rail_clip(page))
    print("settled capsule:", json.dumps(capsule(page), ensure_ascii=False))

    states = page.eval_on_selector_all(
        '[aria-label="按平台筛选"] button',
        "els => els.map(e => ({ v: e.dataset.value, pressed: e.getAttribute('aria-pressed'), state: e.dataset.state }))",
    )
    print("states:", json.dumps(states, ensure_ascii=False))

    # 再点一次同一个平台应该回到「全部」
    page.click('button[data-value="douyin"]')
    page.wait_for_timeout(700)
    print("after toggle off:", json.dumps(capsule(page), ensure_ascii=False))
    print("all pressed:", page.get_attribute('button[data-value="all"]', "aria-pressed"))

    # 暗色
    page.click('button[aria-label="切换到暗色"]')
    page.wait_for_timeout(500)
    page.screenshot(path=str(OUT / "tabrail-dark.png"), clip=rail_clip(page))
    page.screenshot(path=str(OUT / "tabrail-dark-page.png"))
    print("dark page saved")

    browser.close()
