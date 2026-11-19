import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8799"
OUT = ROOT / "design" / "review"
sys.stdout.reconfigure(encoding="utf-8")

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    # 1) 错误态在暗色下
    page.goto(BASE + "/", wait_until="networkidle"); page.wait_for_timeout(900)
    page.click('button[aria-label^="切换到"]'); page.wait_for_timeout(400)
    page.goto(BASE + "/item/nope-nope-nope", wait_until="networkidle"); page.wait_for_timeout(1500)
    st = page.evaluate(""" () => {
      const el = [...document.querySelectorAll('div')].find(d => d.innerText && d.innerText.includes('这条内容打不开'));
      if (!el) return null; const s = getComputedStyle(el);
      return { txt: el.innerText.trim().slice(0,40), color: s.color, bg: s.backgroundColor, border: s.borderTopColor };
    } """)
    print("ERROR dark", json.dumps(st, ensure_ascii=False))
    page.screenshot(path=str(OUT / "error-dark.png"))
    page.click('button[aria-label^="切换到"]'); page.wait_for_timeout(400)
    # 2) 图片灯箱：找带正文图片的条目（V2EX 掌阅 / 小红书）
    page.goto(BASE + "/", wait_until="networkidle"); page.wait_for_timeout(1200)
    page.locator("article", has_text="掌阅").first.click()
    page.wait_for_timeout(2500)
    page.keyboard.press("Tab")
    page.wait_for_timeout(200)
    imgs = page.evaluate("() => [...document.querySelectorAll('main img, article img, .prose img')].length")
    print("content imgs", imgs)
    try:
        page.locator("img").nth(2).click()
        page.wait_for_timeout(600)
        lb = page.evaluate(""" () => {
          const el = [...document.querySelectorAll('div')].find(d => getComputedStyle(d).position === 'fixed' && d.className.includes('bg-black'));
          if (!el) return null;
          return { role: el.getAttribute('role'), ariaModal: el.getAttribute('aria-modal'), tab: el.getAttribute('tabindex'),
                   html: el.outerHTML.slice(0, 160) };
        } """)
        print("LIGHTBOX", json.dumps(lb, ensure_ascii=False))
        page.screenshot(path=str(OUT / "lightbox.png"))
        page.keyboard.press("Escape"); page.wait_for_timeout(400)
        still = page.evaluate("() => [...document.querySelectorAll('div')].some(d => getComputedStyle(d).position === 'fixed' && d.className.includes('bg-black'))")
        print("lightbox after Esc still present?", still)
    except Exception as e:
        print("lightbox try failed", str(e)[:200])
    # 3) 设置页脏状态条
    page.goto(BASE + "/settings", wait_until="networkidle"); page.wait_for_timeout(1200)
    inp = page.locator("input").nth(3)
    inp.fill("30")
    page.wait_for_timeout(500)
    bar = page.evaluate(""" () => {
      const el = [...document.querySelectorAll('div')].find(d => getComputedStyle(d).position === 'fixed' && d.className.includes('bottom-6'));
      if (!el) return null; const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
      return { top: Math.round(r.top), left: Math.round(r.left), w: Math.round(r.width), z: s.zIndex, cls: el.className.slice(0,110) };
    } """)
    print("DIRTY BAR", json.dumps(bar, ensure_ascii=False))
    page.screenshot(path=str(OUT / "settings-dirty.png"))
    b.close()
