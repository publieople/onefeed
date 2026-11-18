"""灯箱别铺满整页：覆盖层必须贴着视口，图要能整张看清，长图能滚。

细节页的 route 容器带 transform，历史上 fixed 子元素会以整页为参照 -> 图被拉到页高、只能看到一截。
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(TMP)

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:8791"
ITEM = "xiaohongshu:note:6ada281a000000002c01b1cc"  # 那些火爆水源的高质量梗图
SHOTS = ROOT / "design"
SHOTS.mkdir(exist_ok=True)

fails = []


def ok(name, cond, extra=""):
    print(("OK   " if cond else "FAIL ") + name.ljust(28) + (str(extra) if extra != "" else ""))
    if not cond:
        fails.append(name)


BOX = """() => {
  const ov = document.querySelector('body > div[class*="fixed"][class*="inset-0"][class*="z-[60]"]');
  if (!ov) return null;
  const img = ov.querySelector('img');
  const scroll = ov.querySelector('div[class*="overflow-auto"]');
  const box = ov.getBoundingClientRect();
  const ib = img ? img.getBoundingClientRect() : null;
  return {
    overlay: [Math.round(box.left), Math.round(box.top), Math.round(box.width), Math.round(box.height)],
    img: ib ? [Math.round(ib.width), Math.round(ib.height)] : null,
    bodyOverflow: getComputedStyle(document.body).overflow,
    scrolls: scroll ? scroll.scrollHeight > scroll.clientHeight + 1 : false,
    inShell: Boolean(ov.closest('.page-shell')),
  };
}"""

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE + "/item/" + ITEM, wait_until="domcontentloaded")
    # 详情默认落在 AI 总结页签，图片在「原文」里
    page.get_by_role("button", name="原文").click()
    page.wait_for_selector('img[src*="/img-0"]', timeout=90000)
    page.wait_for_timeout(600)

    thumb = page.locator('button:has(img[src*="/img-0"])').first
    thumb.click()
    page.wait_for_timeout(400)

    box = page.evaluate(BOX)
    ok("灯箱挂在 body 下、不在页壳里", bool(box) and not box["inShell"], box and box["inShell"])
    ok("覆盖层就是视口大小", box["overlay"] == [0, 0, 1440, 900], box["overlay"])
    ok("图片高度不超过视口", box["img"][1] <= 900, box["img"])
    ok("打开时锁住页面滚动", box["bodyOverflow"] == "hidden", box["bodyOverflow"])
    page.screenshot(path=str(SHOTS / "lightbox-fit.png"))

    # 点图换原尺寸：宽度受限、内容可滚
    page.locator('body > div[class*="z-[60]"] img').click()
    page.wait_for_timeout(400)
    zoom = page.evaluate(BOX)
    ok("原尺寸时宽度不超过视口", zoom["img"][0] <= 1440, zoom["img"])
    ok("原尺寸时容器可滚动", zoom["scrolls"] is True, zoom["scrolls"])
    page.screenshot(path=str(SHOTS / "lightbox-zoom.png"))

    # Esc 关，滚动锁恢复
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    closed = page.evaluate(BOX)
    ok("Esc 能关掉", closed is None)
    ok("关掉后恢复页面滚动", page.evaluate("() => getComputedStyle(document.body).overflow") != "hidden")

    # 右键翻到下一张（if any）
    thumb.click()
    page.wait_for_timeout(400)
    before = page.evaluate("() => document.querySelector('body > div[class*=\"z-[60]\"] img').getAttribute('src')")
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(350)
    after = page.evaluate("() => document.querySelector('body > div[class*=\"z-[60]\"] img')?.getAttribute('src')")
    ok("左右键能翻图", before != after, (str(before)[-12:], str(after)[-12:]))

    # 全站：页壳里不该有 fixed 元素（这次事故的根因）
    stray = page.evaluate(
        "() => Array.from(document.querySelectorAll('.page-shell *')).filter((n) => getComputedStyle(n).position === 'fixed').length"
    )
    ok("页壳里没有 fixed 子元素", stray == 0, stray)

    # 手机宽度：灯箱同样只能占视口，图不能横着流出去
    phone = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    mp = phone.new_page()
    mp.on("pageerror", lambda e: errors.append("phone:" + str(e)))
    mp.goto(BASE + "/item/" + ITEM, wait_until="domcontentloaded")
    mp.get_by_role("button", name="原文").click()
    mp.wait_for_selector('img[src*="/img-0"]', timeout=90000)
    mp.locator('button:has(img[src*="/img-0"])').first.click()
    mp.wait_for_timeout(1500)
    mp.wait_for_function(
        "() => { const i = document.querySelector('body > div[class*=\"z-[60]\"] img'); return i && i.naturalWidth > 0 && i.getBoundingClientRect().width > 100; }",
        timeout=30000,
    )
    mbox = mp.evaluate(BOX)
    ok("手机端灯箱贴着视口", mbox["overlay"] == [0, 0, 390, 844], mbox["overlay"])
    ok("手机端图片不出屏", mbox["img"][0] <= 390 and mbox["img"][1] <= 844, mbox["img"])
    mp.screenshot(path=str(SHOTS / "lightbox-phone.png"))
    phone.close()

    ok("没有页面报错", not errors, errors[:2])
    browser.close()

print("FAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
