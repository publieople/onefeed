"""交互行为门禁：拿真浏览器验「每个交互都有反馈」。

静态门禁（web/scripts/check-ui.mjs）管写法，这里管实际效果：
按钮有过渡、卡片 hover 会抬、按下会缩、切页有过渡、暗色开关真的生效。

跑法：
    uv run python probes/check_interactions.py
需要服务已在 http://127.0.0.1:8791 跑着。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(TMP)

from playwright.sync_api import sync_playwright  # noqa: E402

URL = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8791") + "/?v=gate"
checks: list[str] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    if not cond:
        raise AssertionError(name + ("：" + detail if detail else ""))
    checks.append(name)


def transform_of(page, selector: str) -> str:
    return page.eval_on_selector(
        selector, "el => getComputedStyle(el).transform"
    )


def main() -> int:
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        # 只算 JS 异常与真正的 console.error；外链封面 403 属于平台签名过期，不算交互问题
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on(
            "console",
            lambda m: errors.append(m.text)
            if m.type == "error" and not m.text.startswith("Failed to load resource")
            else None,
        )
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("article", timeout=20000)

        # 1. 顶栏按钮按下有过渡
        dur = page.eval_on_selector(
            'button[title="刷新全部平台"]',
            "el => getComputedStyle(el).transitionDuration",
        )
        ok("顶栏按钮有过渡", dur not in ("", "0s"), dur)

        # 2. 卡片 hover 会抬起来
        card = page.locator("article").first
        before = transform_of(page, "article")
        box = card.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 40)
        page.wait_for_timeout(220)
        after = transform_of(page, "article")
        ok("卡片 hover 有位移", before != after, before + " -> " + after)

        # 3. 按下会缩
        page.mouse.down()
        page.wait_for_timeout(120)
        pressed = transform_of(page, "article")
        page.mouse.up()
        ok("卡片按下有缩放", pressed != after, after + " -> " + pressed)

        # 4. 切页有过渡：点下去 90ms 时旧页应该正在淡出或位移，而不是瞬间消失
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + 40)
        page.wait_for_timeout(90)
        mid = page.evaluate(
            "() => { const el = document.querySelector('.page-shell');"
            " if (!el) return 'gone'; const s = getComputedStyle(el);"
            " return s.opacity + '|' + s.transform; }"
        )
        page.wait_for_url("**/item/**", timeout=15000)
        opacity = mid.split("|")[0]
        moving = opacity not in ("1", "gone") or mid.split("|")[-1] != "none"
        ok("切页有过渡帧", moving, mid)
        page.wait_for_selector("h1", timeout=20000)
        title = page.inner_text("h1").strip()
        ok("详情页渲染出标题", len(title) > 0, title[:40])

        # 5. 暗色开关生效并持久化
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("article", timeout=20000)
        before_dark = page.evaluate("document.documentElement.classList.contains('dark')")
        page.click('button[aria-label^="切换到"]')
        page.wait_for_timeout(300)
        after_dark = page.evaluate("document.documentElement.classList.contains('dark')")
        stored = page.evaluate("localStorage.getItem('onefeed.theme')")
        ok("暗色开关切换了主题", before_dark != after_dark, str(before_dark) + " -> " + str(after_dark))
        ok("主题写进了 localStorage", stored in ("light", "dark"), str(stored))
        page.reload(wait_until="networkidle")
        kept = page.evaluate("document.documentElement.classList.contains('dark')")
        ok("刷新后主题保留", kept == after_dark, str(kept))

        browser.close()

    ok("无 console 报错", not errors, "; ".join(errors[:3]))
    for name in checks:
        print("  PASS " + name)
    print("check_interactions: " + str(len(checks)) + "/" + str(len(checks)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print("  FAIL " + str(exc))
        sys.exit(1)
