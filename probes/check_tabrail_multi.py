"""胶囊多选的行为验证：单击替换、Ctrl 加减、Shift 选一段、宽度不被拉满。"""
import json
import os
import sys

TMP = os.path.join(r"E:\Documents\deepseek-harness\default-workspace\onefeed", ".onefeed", "tmp")
os.makedirs(TMP, exist_ok=True)
for name in ("TMP", "TEMP", "TMPDIR"):
    os.environ[name] = TMP

from playwright.sync_api import sync_playwright  # noqa: E402

URL = "http://127.0.0.1:8791/"
SELECTED = "[data-value][aria-pressed='true']"


def pressed(page):
    """只返回平台项；「全部」在没选平台时本来就是按下态，单独查。"""
    return page.eval_on_selector_all(
        "[data-value]", "els => els.filter(e => e.getAttribute('aria-pressed') === 'true' && e.dataset.value !== 'all').map(e => e.dataset.value)"
    )


def all_on(page):
    return page.get_attribute('[data-value="all"]', "aria-pressed") == "true"


def rail_box(page):
    return page.evaluate(
        """() => {
          const group = document.querySelector('[role=group][aria-label^="按平台筛选"]');
          const outer = group.parentElement;
          return { outer: outer.getBoundingClientRect().width, inner: group.scrollWidth, viewport: innerWidth };
        }"""
    )


def indicator_x(page):
    return page.evaluate(
        """() => {
          const group = document.querySelector('[role=group][aria-label^="按平台筛选"]');
          const pill = group.querySelector('span.absolute');
          return pill ? Math.round(pill.getBoundingClientRect().x * 100) / 100 : null;
        }"""
    )


def main():
    checks = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("[data-value]", timeout=15000)

        box = rail_box(page)
        checks.append(("胶囊宽度贴合内容", box["outer"] < 1000 and box["outer"] <= box["viewport"]))
        checks.append(("初始全部", pressed(page) == [] and all_on(page)))

        page.click('[data-value="bilibili"]')
        checks.append(("单击只选一个", pressed(page) == ["bilibili"]))

        page.click('[data-value="douyin"]', modifiers=["Control"])
        two = pressed(page)
        checks.append(("Ctrl 追加", sorted(two) == ["bilibili", "douyin"]))

        page.click('[data-value="zhihu"]', modifiers=["Shift"])
        rng = pressed(page)
        checks.append(("Shift 选一段", rng == ["douyin", "juejin", "v2ex", "zhihu"]))
        page.screenshot(path=os.path.join(r"E:\Documents\deepseek-harness\default-workspace\onefeed", "design", "tabrail-multi.png"), clip={"x": 0, "y": 100, "width": 1440, "height": 120})

        page.click('[data-value="douyin"]', modifiers=["Control"])
        checks.append(("Ctrl 取消一个", "douyin" not in pressed(page) and len(pressed(page)) == 3))

        page.click('[data-value="juejin"]')
        checks.append(("普通单击替换为单个", pressed(page) == ["juejin"]))

        page.click('[data-value="juejin"]')
        checks.append(("再点自己回到全部", pressed(page) == [] and all_on(page)))

        page.click('[data-value="bilibili"]')
        x1 = indicator_x(page)
        page.click('[data-value="zhihu"]')
        page.wait_for_timeout(420)
        x2 = indicator_x(page)
        checks.append(("高亮胶囊跟着移动", x1 is not None and x2 is not None and abs(x2 - x1) > 50))

        page.click('[data-value="all"]')
        checks.append(("点全部清空", pressed(page) == [] and all_on(page)))
        checks.append(("无控制台报错", not errors))

        browser.close()

    ok = all(flag for _, flag in checks)
    print(json.dumps({"ok": ok, "checks": [{"name": n, "pass": f} for n, f in checks], "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
