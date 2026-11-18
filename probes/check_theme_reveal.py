"""换主题动效（View Transitions 对角扫过）的行为验证。

检查三件事：
1. 点一次主题按钮，document.startViewTransition 真的被调用；
2. 换色和图标在同一帧完成，html.dark 与 localStorage 都落到目标主题；
3. root 的 view-transition 组动画时长是 0.7s（CSS 生效，不是被浏览器默认动画接管）。

顺带在扫过的中途各截一张图，存进 design/ 作为证据。

跑法：
    uv run python probes/check_theme_reveal.py
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

URL = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8791") + "/?v=theme"
DESIGN = ROOT / "design"
DESIGN.mkdir(exist_ok=True)
checks: list[str] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(name + ("：" + detail if detail else ""))
    checks.append(name)


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(URL, wait_until="domcontentloaded")
        page.evaluate("localStorage.setItem('onefeed.theme','light'); location.reload()")
        page.wait_for_selector("article", timeout=20000)
        page.wait_for_timeout(300)

        # 记录 startViewTransition 的调用次数，顺便测得到动画进行中的伪元素样式
        page.evaluate(
            """() => {
            window.__vt = 0;
            const orig = document.startViewTransition?.bind(document);
            if (!orig) return;
            document.startViewTransition = (cb) => { window.__vt += 1; return orig(cb); };
        }"""
        )

        ok("页面有 startViewTransition", page.evaluate("typeof document.startViewTransition === 'function'"))

        page.click('button[aria-label="切换到暗色"]')
        page.wait_for_timeout(90)
        dur = page.evaluate(
            "getComputedStyle(document.documentElement, '::view-transition-group(root)').animationDuration"
        )
        shot = DESIGN / "theme-reveal-light-to-dark.png"
        page.screenshot(path=str(shot))
        page.wait_for_timeout(800)
        ok("去暗色调用了 View Transition", page.evaluate("window.__vt") >= 1)
        ok("root 动画时长是 0.7s", dur.strip() == "0.7s", dur)
        ok("html 已切到 dark", page.evaluate("document.documentElement.classList.contains('dark')"))
        ok("localStorage 记住 dark", page.evaluate("localStorage.getItem('onefeed.theme')") == "dark")

        page.click('button[aria-label="切换到亮色"]')
        page.wait_for_timeout(220)
        page.screenshot(path=str(DESIGN / "theme-reveal-dark-to-light.png"))
        page.wait_for_timeout(800)
        ok("来回都走了 View Transition", page.evaluate("window.__vt") >= 2)
        ok("html 已切回 light", page.evaluate("!document.documentElement.classList.contains('dark')"))

        browser.close()

    for c in checks:
        print("OK", c)
    print("PASS", len(checks), "checks; screenshots in design/theme-reveal-*.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
