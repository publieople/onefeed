
import os, sys, json, time
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
_tmp = str(ROOT / ".onefeed" / "tmp")
os.environ["TMP"] = _tmp
os.environ["TEMP"] = _tmp
os.environ["TMPDIR"] = _tmp
for k in ("TMP", "TEMP", "TMPDIR"):
    Path(os.environ[k]).mkdir(parents=True, exist_ok=True)

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8791"
URL = BASE + "/"
OUT = ROOT / "design"
fails = []
def check(name, ok, extra=""):
    print(("OK   " if ok else "FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not ok: fails.append(name)

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    page = b.new_page(viewport={"width":1440,"height":900})
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_selector('[data-vt-item]', timeout=30000)

    # 1) 点 B 站胶囊
    chip = page.get_by_role("button", name="B 站 140").first
    if chip.count() == 0:
        chip = page.locator('button:has-text("B 站")').first
    chip.click()
    page.wait_for_timeout(900)
    u1 = page.url
    check("点 B 站后 URL 带 p=bilibili", "p=bilibili" in u1, u1)
    pressed = page.evaluate("""() => Array.from(document.querySelectorAll('button[aria-pressed="true"]')).map(b => b.textContent.trim())""")
    check("B 站胶囊 aria-pressed", any("B 站" in t for t in pressed), pressed)
    count_text = page.locator("p.mt-4").first.inner_text()
    check("摘要行显示筛选结果", count_text.startswith("筛选出"), count_text)
    first_id = page.evaluate("""() => document.querySelector('[data-vt-item]')?.getAttribute('data-vt-item')""")
    page.screenshot(path=str(OUT / "feed-filter-kept-1.png"))

    # 2) 点开第一张卡
    page.locator('[data-vt-item]').first.click()
    page.wait_for_url("**/item/**", timeout=15000)
    page.wait_for_timeout(700)
    check("已进入详情页", "/item/" in page.url, page.url)

    # 3) 点返回
    page.locator('button:has-text("返回")').first.click()
    page.wait_for_timeout(1200)
    u2 = page.url
    check("返回后 URL 仍带筛选条件", "p=bilibili" in u2, u2)
    pressed2 = page.evaluate("""() => Array.from(document.querySelectorAll('button[aria-pressed="true"]')).map(b => b.textContent.trim())""")
    check("返回后胶囊仍选中 B 站", any("B 站" in t for t in pressed2), pressed2)
    count2 = page.locator("p.mt-4").first.inner_text()
    check("返回后仍是筛选结果", count2.startswith("筛选出"), count2)
    back_exists = page.evaluate("""(id) => !!document.querySelector('[data-vt-item="' + CSS.escape(id) + '"]')""", first_id)
    check("被点的那张卡还在列表里", back_exists, first_id)
    rect = page.evaluate("""(id) => { const el = document.querySelector('[data-vt-item="' + CSS.escape(id) + '"]'); if (!el) return null; const r = el.getBoundingClientRect(); return {top: Math.round(r.top), bottom: Math.round(r.bottom)}; }""", first_id)
    check("返回落点在视野内", bool(rect) and rect["top"] < 900 and rect["bottom"] > 60, rect)
    page.screenshot(path=str(OUT / "feed-filter-kept-2.png"))

    # 4) 浏览器后退键路径
    page.locator('[data-vt-item]').first.click()
    page.wait_for_url("**/item/**", timeout=15000)
    page.wait_for_timeout(500)
    page.go_back()
    page.wait_for_timeout(1200)
    check("浏览器后退也带筛选", "p=bilibili" in page.url, page.url)
    pressed3 = page.evaluate("""() => Array.from(document.querySelectorAll('button[aria-pressed="true"]')).map(b => b.textContent.trim())""")
    check("浏览器后退胶囊仍选中", any("B 站" in t for t in pressed3), pressed3)

    # 5) 深链：平台 + 关键词 + 时间范围 一起生效
    page.goto(BASE + "/?p=bilibili&q=AI&range=today", wait_until="domcontentloaded")
    page.wait_for_timeout(1800)
    t = page.locator("p.mt-4").first.inner_text()
    check("深链直接带条件生效", t.startswith("筛选出"), t)
    pressed5 = page.evaluate("""() => Array.from(document.querySelectorAll('button[aria-pressed="true"]')).map(b => b.textContent.trim())""")
    check("深链里 今天 也选中", any("今天" in x for x in pressed5), pressed5)
    check("深链里 B 站 也选中", any("B 站" in x for x in pressed5), pressed5)

    # 6) 排序也进 URL，往返不丢
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_selector('[data-vt-item]', timeout=30000)
    page.get_by_role("button", name="按热度").click()
    page.wait_for_timeout(1200)
    check("点按热度后 URL 带 sort", "sort=engagement" in page.url, page.url)
    page.locator('[data-vt-item]').first.click()
    page.wait_for_url("**/item/**", timeout=15000)
    page.wait_for_timeout(400)
    page.locator('button:has-text("返回")').first.click()
    page.wait_for_timeout(1200)
    check("返回后排序保留", "sort=engagement" in page.url, page.url)
    pressed6 = page.evaluate("""() => Array.from(document.querySelectorAll('button[aria-pressed="true"]')).map(b => b.textContent.trim())""")
    check("返回后 按热度 仍选中", any("热度" in x for x in pressed6), pressed6)

    # 7) 多选（Ctrl 加选）往返不丢
    page.goto(BASE + "/", wait_until="domcontentloaded")
    page.wait_for_selector('[data-vt-item]', timeout=30000)
    page.locator('button:has-text("B 站")').first.click()
    page.wait_for_timeout(600)
    page.locator('button:has-text("掘金")').first.click(modifiers=["Control"])
    page.wait_for_timeout(900)
    check("Ctrl 多选写进 URL", "p=bilibili%2Cjuejin" in page.url or "p=bilibili,juejin" in page.url, page.url)
    page.locator('[data-vt-item]').first.click()
    page.wait_for_url("**/item/**", timeout=15000)
    page.wait_for_timeout(400)
    page.locator('button:has-text("返回")').first.click()
    page.wait_for_timeout(1200)
    pressed7 = page.evaluate("""() => Array.from(document.querySelectorAll('button[aria-pressed="true"]')).map(b => b.textContent.trim())""")
    check("返回后多选两项都在", sum(1 for x in pressed7 if ("B 站" in x or "掘金" in x)) == 2, pressed7)

    # 8) 空态往返仍为空态，不塌回全量
    page.goto(BASE + "/?p=bilibili&q=zzzznotfound", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    empty = page.locator("p.mt-4").first.inner_text()
    check("空态显示 0 命中", "0 条" in empty, empty)

    # 9) 列表滚到很下面再点开，返回要滚回那张卡（不是回顶部）
    page.goto(BASE + "/?p=bilibili", wait_until="domcontentloaded")
    page.wait_for_selector('[data-vt-item]', timeout=30000)
    page.mouse.wheel(0, 4000)
    page.wait_for_timeout(800)
    deep = page.evaluate("""() => {
      const els = Array.from(document.querySelectorAll('[data-vt-item]'));
      const vh = window.innerHeight;
      const el = els.filter(e => { const r = e.getBoundingClientRect(); return r.top > 100 && r.bottom < vh - 40; }).pop() || els[els.length - 1];
      const r = el.getBoundingClientRect();
      return { id: el.getAttribute('data-vt-item'), top: Math.round(r.top) };
    }""")
    check("滚动后点到的是靠下的卡", deep["top"] > 150, deep)
    # data-vt-item 挂在网格单元上，真正可点的是它里面的卡片（article）
    page.evaluate("""(id) => { const cell = document.querySelector('[data-vt-item="' + CSS.escape(id) + '"]'); (cell.querySelector('article') || cell).click(); }""", deep["id"])
    page.wait_for_url("**/item/**", timeout=15000)
    page.wait_for_timeout(600)
    check("进详情页在顶部", page.evaluate("() => window.scrollY") < 5, page.evaluate("() => window.scrollY"))
    page.locator('button:has-text("返回")').first.click()
    page.wait_for_timeout(1400)
    scroll_y = page.evaluate("() => Math.round(window.scrollY)")
    check("返回后不是回到顶部", scroll_y > 100, scroll_y)
    rect9 = page.evaluate("""(id) => { const el = document.querySelector('[data-vt-item="' + CSS.escape(id) + '"]'); if (!el) return null; const r = el.getBoundingClientRect(); return {top: Math.round(r.top), bottom: Math.round(r.bottom)}; }""", deep["id"])
    check("返回后那张卡在视野里", bool(rect9) and rect9["top"] < 900 and rect9["bottom"] > 60, rect9)
    page.screenshot(path=str(OUT / "feed-filter-kept-3.png"))

    check("无 pageerror", len(errs) == 0, errs[:2])
    b.close()

print("FAILED:", fails if fails else "none")
sys.exit(1 if fails else 0)
