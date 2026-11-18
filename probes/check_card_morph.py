"""点卡片 → 卡片长大铺满整页；返回 → 详情页缩回卡片。

尺寸从 View Transition 的伪元素（of-card 的 old/new）里逐帧读，不靠猜。
采样放在页面里用 requestAnimationFrame 做：截图一张要 150ms 以上，循环里截图会把
时间戳拖到动画结束之后，量出来的数字全是残影。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8791"
OUT = Path(__file__).resolve().parent.parent / "design"
TMP = Path(__file__).resolve().parent.parent / ".onefeed" / "tmp"

# 在页面里逐帧记 old/new 的宽高与透明度，时间基准取 html.nav-vt 出现的那一刻
SAMPLE = """() => {
  const d = document.documentElement;
  const g = (n, s) => {
    const cs = getComputedStyle(d, '::view-transition-' + s + '(' + n + ')');
    return { w: parseFloat(cs.width) || 0, h: parseFloat(cs.height) || 0, o: parseFloat(cs.opacity || '1') };
  };
  window.__samples = [];
  let t0 = null;
  const tick = () => {
    if (d.classList.contains('nav-vt')) {
      if (t0 === null) { t0 = performance.now(); window.__samples = []; }
      window.__samples.push({ t: Math.round(performance.now() - t0), old: g('of-card', 'old'), new: g('of-card', 'new') });
    }
    if (t0 === null || performance.now() - t0 < 950) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}"""


def main() -> int:
    TMP.mkdir(parents=True, exist_ok=True)
    # Playwright 的 node driver 用 TEMP 建临时目录，用户级 Temp 在这台机器上不可写
    for key in ("TMP", "TEMP", "TMPDIR"):
        os.environ[key] = str(TMP)
    results: list[tuple[str, bool, str]] = []

    def ok(name: str, cond: bool, detail: object = "") -> None:
        results.append((name, bool(cond), str(detail)))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE + "/?v=morph3", wait_until="networkidle")
        page.wait_for_selector("article", timeout=20000)
        box = page.locator("article").first.bounding_box()
        assert box
        cw = box["width"]

        # 记录 startViewTransition 调用次数
        page.evaluate("() => { window.__vt = 0; const o = document.startViewTransition.bind(document); document.startViewTransition = (cb) => { window.__vt++; return o(cb); }; }")

        page.evaluate(SAMPLE)
        page.locator("article").first.click()
        page.wait_for_timeout(1100)
        # 头一两帧伪元素还没量到几何（占位是 100×0），只留真正有尺寸的帧
        frames = [f for f in page.evaluate("() => window.__samples") if f["old"]["w"] >= 150 and f["old"]["h"] >= 100]
        page.wait_for_timeout(200)
        print("enter:", json.dumps(frames[:3] + frames[-3:], ensure_ascii=False))

        ok("点卡片走了 View Transition", page.evaluate("() => window.__vt") == 1)
        ok("地址进了详情页", "/item/" in page.url, page.url)
        ok("详情页根部带着 of-card",
           page.evaluate("() => getComputedStyle(document.querySelector('[style*=\"view-transition-name\"]') || document.body).viewTransitionName") == "of-card")
        ok("过渡结束后清掉 nav-vt", "nav-vt" not in page.evaluate("() => document.documentElement.className"))
        ok("采样够密", len(frames) >= 20, len(frames))

        first = frames[0]
        widest = max(f["old"]["w"] for f in frames)
        last = frames[-1]
        ok("起手就是卡片那么宽", abs(first["old"]["w"] - cw) <= cw * 0.12, (round(first["old"]["w"], 1), cw))
        ok("中间长到卡片的两倍以上", any(f["old"]["w"] > cw * 1.8 for f in frames), widest)
        ok("最后铺到整页宽", widest >= 1080, widest)
        ok("起点到终点是单调长大", frames[len(frames) // 2]["old"]["w"] > first["old"]["w"] * 2, [round(f["old"]["w"]) for f in frames[:3]])
        ok("前段旧页还不透明", first["old"]["o"] > 0.9, first["old"]["o"])
        ok("收尾时旧页淡出、新页到位", last["old"]["o"] < 0.1 and last["new"]["o"] > 0.9, [last["old"]["o"], last["new"]["o"]])

        # 返回方向
        page.evaluate(SAMPLE)
        page.get_by_role("button", name="返回").click()
        page.wait_for_timeout(1100)
        back = [f for f in page.evaluate("() => window.__samples") if f["old"]["w"] >= 150 and f["old"]["h"] >= 100]
        page.wait_for_timeout(200)
        print("back:", json.dumps(back[:2] + back[-2:], ensure_ascii=False))

        ok("返回走了 View Transition", page.evaluate("() => window.__vt") == 2)
        # 返回会带回进来时那一屏（可能带 ?p=...&q=...），只看路径是不是首页
        ok("返回回到信息流", page.url.split("?")[0].rstrip("/").endswith(":8791"), page.url)
        ok("返回目标卡片在场上且叫 of-card",
           page.evaluate("() => { const el = document.querySelector('[data-vt-item]'); return !!el && !!el.querySelector('[style*=\"view-transition-name\"]'); }"))
        b_first, b_last = back[0], back[-1]
        b_narrow = min(f["old"]["w"] for f in back)
        ok("退场从整页宽开始", b_first["old"]["w"] >= 1080, round(b_first["old"]["w"], 1))
        ok("退场一路缩回卡片", b_narrow <= cw * 1.15, (round(b_narrow, 1), cw))
        ok("退场收尾时信息流已就位", b_last["new"]["o"] > 0.9, b_last["new"]["o"])
        ok("没有页面报错", not errors, errors[:1])

        # 截图单独一轮，避免截图耗时污染采样
        for ms, tag in ((120, "enter-120"), (260, "enter-260")):
            page.goto(BASE + "/?v=shot", wait_until="networkidle")
            page.wait_for_selector("article", timeout=20000)
            page.locator("article").first.click()
            page.wait_for_timeout(ms)
            page.screenshot(path=str(OUT / ("morph-" + tag + ".png")))
        page.wait_for_timeout(1200)
        page.get_by_role("button", name="返回").click()
        page.wait_for_timeout(150)
        page.screenshot(path=str(OUT / "morph-back-150.png"))
        page.wait_for_timeout(150)
        page.screenshot(path=str(OUT / "morph-back-300.png"))

        browser.close()

    width = max(len(n) for n, _, _ in results)
    for name, passed, detail in results:
        print(("OK  " if passed else "FAIL") + " " + name.ljust(width) + ("  " + detail if detail and not passed else ""))
    failed = [r for r in results if not r[1]]
    print(("FAILED " + str(len(failed))) if failed else "PASS " + str(len(results)) + " checks; screenshots in design/morph-*.png")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
