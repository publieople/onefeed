"""胶囊多选的行为验证：单击替换、Ctrl 加减、Shift 选一段、连续段合并、宽度不被拉满。"""
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


def runs(page):
    """每个黑胶囊（连续段）含哪些平台、多宽；顺带返回这些平台的单枚宽度之和。"""
    return page.evaluate(
        """() => {
          const group = document.querySelector('[role=group][aria-label^="按平台筛选"]');
          const btns = [...group.querySelectorAll('[data-value]')];
          const byParent = new Map();
          for (const b of btns) {
            const p = b.parentElement;
            if (!p.classList.contains('bg-solid')) continue;
            if (!byParent.has(p)) byParent.set(p, []);
            byParent.get(p).push(b);
          }
          return [...byParent.values()].map(list => ({
            ids: list.map(b => b.dataset.value),
            width: Math.round(list[0].parentElement.getBoundingClientRect().width * 10) / 10,
            chips: Math.round(list.reduce((s, b) => s + b.getBoundingClientRect().width, 0) * 10) / 10,
            x: Math.round(list[0].parentElement.getBoundingClientRect().x * 10) / 10,
          }));
        }"""
    )


def main():
    checks = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("[data-value]", timeout=15000)

        box = rail_box(page)
        checks.append(("胶囊宽度贴合内容", box["outer"] < 1000 and box["outer"] <= box["viewport"]))
        checks.append(("初始全部", pressed(page) == [] and all_on(page)))

        page.click('[data-value="bilibili"]')
        page.wait_for_timeout(300)
        checks.append(("单击只选一个", pressed(page) == ["bilibili"] and len(runs(page)) == 1))

        # 平台顺序：全部 / B 站 / 小红书 / 抖音 / 掘金 / V2EX / 知乎 / 知乎热榜
        page.click('[data-value="xiaohongshu"]', modifiers=["Control"])
        page.wait_for_timeout(420)
        merged = runs(page)
        checks.append((
            "相邻两项并成一条",
            pressed(page) == ["bilibili", "xiaohongshu"]
            and len(merged) == 1 and merged[0]["ids"] == ["bilibili", "xiaohongshu"]
            and abs(merged[0]["width"] - merged[0]["chips"]) <= 8,
        ))

        page.click('[data-value="douyin"]', modifiers=["Control"])
        page.click('[data-value="juejin"]', modifiers=["Control"])
        page.wait_for_timeout(420)
        four = runs(page)
        checks.append((
            "四项连续仍是一条",
            len(four) == 1 and four[0]["ids"] == ["bilibili", "xiaohongshu", "douyin", "juejin"]
            and abs(four[0]["width"] - four[0]["chips"]) <= 8,
        ))

        page.click('[data-value="xiaohongshu"]', modifiers=["Control"])
        page.wait_for_timeout(420)
        split = runs(page)
        checks.append((
            "挖掉中间一项劈成两条",
            len(split) == 2
            and [seg["ids"] for seg in split] == [["bilibili"], ["douyin", "juejin"]],
        ))

        page.click('[data-value="bilibili"]')
        page.click('[data-value="v2ex"]', modifiers=["Shift"])
        rng = pressed(page)
        checks.append(("Shift 选一段", rng == ["bilibili", "xiaohongshu", "douyin", "juejin", "v2ex"]))
        page.wait_for_timeout(420)
        seg = runs(page)
        checks.append(("选段连成一条", len(seg) == 1 and abs(seg[0]["width"] - seg[0]["chips"]) <= 8))
        page.screenshot(path=os.path.join(r"E:\Documents\deepseek-harness\default-workspace\onefeed", "design", "tabrail-multi.png"), clip={"x": 0, "y": 100, "width": 1440, "height": 120})

        page.click('[data-value="juejin"]', modifiers=["Control"])
        page.wait_for_timeout(420)
        after = runs(page)
        checks.append((
            "Shift 段里取消一项也劈开",
            [seg["ids"] for seg in after] == [["bilibili", "xiaohongshu", "douyin"], ["v2ex"]]
            and len(pressed(page)) == 4,
        ))

        page.click('[data-value="juejin"]')
        checks.append(("普通单击替换为单个", pressed(page) == ["juejin"]))

        page.click('[data-value="juejin"]')
        checks.append(("再点自己回到全部", pressed(page) == [] and all_on(page)))

        page.click('[data-value="all"]')
        checks.append(("点全部清空", pressed(page) == [] and all_on(page)))
        checks.append(("无控制台报错", not errors))

        browser.close()

    ok = all(flag for _, flag in checks)
    print(json.dumps({"ok": ok, "checks": [{"name": n, "pass": f} for n, f in checks], "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
