"""卡片 → 详情缩放动效的行为验证。

要验的是四件事：
1. 点卡片时 document.startViewTransition 真的被调用，地址进了详情页；
2. 被点的卡片单独成组（of-card），0.7s、expo-out，放大到 1.075 再淡出；
3. 返回时反向：详情整页缩一点退场，信息流长回来；
4. 不支持 View Transition / 用户关了动效时，直接跳、不报错。

跑法：
    uv run python probes/check_card_morph.py
需要服务已在 http://127.0.0.1:8791 跑着。
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(TMP)

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8791")
URL = BASE + "/?v=morph"
DESIGN = ROOT / "design"
DESIGN.mkdir(exist_ok=True)
checks: list[str] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(name + ("：" + detail if detail else ""))
    checks.append(name)


PATCH_VT = """() => {
    window.__vt = 0;
    const orig = document.startViewTransition?.bind(document);
    if (orig) document.startViewTransition = (cb) => { window.__vt += 1; return orig(cb); };
}"""

PSEUDO = "getComputedStyle(document.documentElement, %s)"


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)

        # 场景一：正常环境，卡片放大 → 进详情 → 返回
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_selector("article", timeout=20000)
        page.wait_for_timeout(400)
        page.evaluate(PATCH_VT)

        page.locator("article").first.click()
        page.wait_for_timeout(90)
        page.screenshot(path=str(DESIGN / "card-morph-lift.png"))
        page.wait_for_timeout(110)
        dur = page.evaluate(PSEUDO % "'::view-transition-group(of-card)'" + ".animationDuration")
        curve = page.evaluate(PSEUDO % "'::view-transition-old(of-card)'" + ".animationTimingFunction")
        name = page.evaluate(PSEUDO % "'::view-transition-old(of-card)'" + ".animationName")
        transform = page.evaluate(PSEUDO % "'::view-transition-old(of-card)'" + ".transform")
        page.screenshot(path=str(DESIGN / "card-morph-enter.png"))
        ok("点卡片走了 View Transition", page.evaluate("window.__vt") >= 1)
        ok("地址进了详情页", "/item/" in page.url, page.url)
        ok("过渡期间 html 带 nav-vt", page.evaluate("document.documentElement.classList.contains('nav-vt')"))
        ok("卡片组动画时长 0.7s", dur.strip() == "0.7s", dur)
        ok("缓动是 expo-out", "0.16" in curve, curve)
        ok("旧卡片动画是 nav-card-lift", name.strip() == "nav-card-lift", name)
        ok("卡片确实被放大了", transform.startswith("matrix(1.0") and transform != "matrix(1, 0, 0, 1, 0, 0)", transform)

        page.wait_for_timeout(900)
        ok("过渡结束清掉 nav-vt", page.evaluate("!document.documentElement.classList.contains('nav-vt')"))

        page.get_by_role("button", name="返回").first.click()
        page.wait_for_timeout(200)
        back_dur = page.evaluate(PSEUDO % "'::view-transition-group(of-page)'" + ".animationDuration")
        back_name = page.evaluate(PSEUDO % "'::view-transition-old(of-page)'" + ".animationName")
        page.screenshot(path=str(DESIGN / "card-morph-back.png"))
        ok("返回也走 View Transition", page.evaluate("window.__vt") >= 2)
        ok("返回回到信息流", page.url.rstrip("/") == BASE, page.url)
        ok("详情页退场组存在", back_name.strip() == "nav-page-down", back_name)
        ok("退场时长 0.55s", back_dur.strip() == "0.55s", back_dur)
        page.wait_for_timeout(900)
        ctx.close()

        # 场景二：不支持 View Transition（模拟老浏览器）
        old = browser.new_context(viewport={"width": 1440, "height": 900})
        old.add_init_script(
            "Object.defineProperty(Document.prototype, 'startViewTransition', { value: undefined, configurable: true });"
        )
        opage = old.new_page()
        opage.on("pageerror", lambda e: errors.append(str(e)))
        opage.goto(URL, wait_until="domcontentloaded")
        opage.wait_for_selector("article", timeout=20000)
        opage.locator("article").first.click()
        opage.wait_for_timeout(600)
        ok("不支持 VT 时照样跳转", "/item/" in opage.url, opage.url)
        ok("不支持 VT 时不留 nav-vt", opage.evaluate("!document.documentElement.classList.contains('nav-vt')"))
        opage.get_by_role("button", name="返回").first.click()
        opage.wait_for_timeout(400)
        ok("不支持 VT 时也能返回", opage.url.rstrip("/") == BASE, opage.url)
        old.close()

        # 场景三：系统开了「减少动态效果」
        calm = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        cpage = calm.new_page()
        cpage.on("pageerror", lambda e: errors.append(str(e)))
        cpage.goto(URL, wait_until="domcontentloaded")
        cpage.wait_for_selector("article", timeout=20000)
        cpage.evaluate(PATCH_VT)
        cpage.locator("article").first.click()
        cpage.wait_for_timeout(500)
        ok("减少动效时不走 View Transition", cpage.evaluate("window.__vt") == 0)
        ok("减少动效时照常进详情", "/item/" in cpage.url, cpage.url)
        calm.close()

        browser.close()

    ok("没有页面报错", not errors, "; ".join(errors[:3]))
    for c in checks:
        print("OK", c)
    print("PASS", len(checks), "checks; screenshots in design/card-morph-*.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
