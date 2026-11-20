from __future__ import annotations
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
out: dict = {}

LIST = r"""() => {
  const all = [...document.querySelectorAll('[data-smooth-scroll]')]
    .filter(el => el.offsetParent !== null && el.scrollHeight - el.clientHeight > 30);
  const el = all[0];
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {top: el.scrollTop, max: el.scrollHeight - el.clientHeight,
          x: r.x + r.width / 2, y: r.y + Math.min(r.height - 20, 240)};
}"""

with sync_playwright() as pw:
    br = pw.chromium.launch(channel="chrome", headless=True,
        args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding",
              "--disable-backgrounding-occluded-windows"])

    # ---- 1) 侧栏到底/到顶时，滚轮交还页面（I-04）----
    page = br.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("a[href^='/item/']", timeout=20000)
    page.wait_for_timeout(1800)
    info = page.evaluate(LIST)
    out["list"] = info
    if info:
        page.evaluate("() => { const el=[...document.querySelectorAll('[data-smooth-scroll]')].filter(e=>e.offsetParent!==null&&e.scrollHeight-e.clientHeight>30)[0]; el.scrollTo({top: el.scrollHeight, behavior:'instant'}); }")
        page.wait_for_timeout(400)
        out["before_bottom"] = {"list": page.evaluate("() => Math.round([...document.querySelectorAll('[data-smooth-scroll]')].filter(e=>e.offsetParent!==null&&e.scrollHeight-e.clientHeight>30)[0].scrollTop)"),
                                "win": page.evaluate("() => Math.round(window.scrollY)")}
        page.mouse.move(info["x"], info["y"])
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(900)
        out["after_bottom_wheel"] = {"list": page.evaluate("() => Math.round([...document.querySelectorAll('[data-smooth-scroll]')].filter(e=>e.offsetParent!==null&&e.scrollHeight-e.clientHeight>30)[0].scrollTop)"),
                                     "win": page.evaluate("() => Math.round(window.scrollY)")}
    # ---- 2) 中段：滚轮归侧栏，页面不动 ----
    page.evaluate("() => window.scrollTo(0, 0)")
    page.evaluate("() => { const el=[...document.querySelectorAll('[data-smooth-scroll]')].filter(e=>e.offsetParent!==null&&e.scrollHeight-e.clientHeight>30)[0]; el.scrollTo({top: 120, behavior:'instant'}); }")
    page.wait_for_timeout(300)
    if info:
        page.mouse.move(info["x"], info["y"])
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(900)
    out["mid_wheel"] = {"list": page.evaluate("() => Math.round([...document.querySelectorAll('[data-smooth-scroll]')].filter(e=>e.offsetParent!==null&&e.scrollHeight-e.clientHeight>30)[0].scrollTop)"),
                        "win": page.evaluate("() => Math.round(window.scrollY)")}
    page.close()

    # ---- 3) 模态锁 html：? 帮助层 ----
    page = br.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("a[href^='/item/']", timeout=20000)
    page.wait_for_timeout(1500)
    page.evaluate("() => window.scrollTo(0, 400)")
    page.wait_for_timeout(300)
    page.keyboard.press("?")
    page.wait_for_timeout(500)
    out["help_open"] = page.evaluate("() => Boolean(document.querySelector('[aria-label=\"键盘快捷键\"]'))")
    page.mouse.move(700, 500)
    page.mouse.wheel(0, 600)
    page.wait_for_timeout(800)
    out["help_lock"] = {"y": page.evaluate("() => Math.round(window.scrollY)"),
                        "html_overflow": page.evaluate("() => getComputedStyle(document.documentElement).overflow")}
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    out["help_closed"] = page.evaluate("() => !document.querySelector('[aria-label=\"键盘快捷键\"]')")
    out["help_restore"] = {"overflow": page.evaluate("() => getComputedStyle(document.documentElement).overflow"),
                           "y": page.evaluate("() => Math.round(window.scrollY)")}
    page.close()

    # ---- 4) 灯箱锁 html ----
    page = br.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("a[href^='/item/']", timeout=20000)
    page.wait_for_timeout(800)
    href = page.evaluate("""async () => {
      const r = await fetch('/api/feed?platform=xiaohongshu&limit=6');
      const j = await r.json();
      const hit = (j.items || []).find(i => (i.summary && i.summary.images > 0) || i.kind === 'images');
      return hit ? '/item/' + encodeURIComponent(hit.id) : null;
    }""")
    out["lightbox_href"] = href
    if href:
        page.goto(BASE + href, wait_until="domcontentloaded")
        page.wait_for_timeout(2200)
        # 切到「原文」
        page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='原文'); b && b.click(); }""")
        page.wait_for_timeout(900)
        thumb = page.evaluate("""() => { const b=document.querySelector('[data-lb-index]'); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        out["thumb"] = thumb
        if thumb:
            page.mouse.click(thumb["x"], thumb["y"])
            page.wait_for_timeout(600)
            out["lb_open"] = page.evaluate("() => Boolean(document.querySelector('[aria-label=\"看图\"]'))")
            y0 = page.evaluate("() => Math.round(window.scrollY)")
            page.mouse.move(700, 500)
            page.mouse.wheel(0, 600)
            page.wait_for_timeout(800)
            out["lb_lock"] = {"y_before": y0, "y_after": page.evaluate("() => Math.round(window.scrollY)"),
                              "html_overflow": page.evaluate("() => getComputedStyle(document.documentElement).overflow")}
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            out["lb_closed"] = page.evaluate("() => !document.querySelector('[aria-label=\"看图\"]')")
    page.close()

    # ---- 5) 确认框（/market 卸载）在页中打开时锁滚动 ----
    page = br.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE + "/market", wait_until="domcontentloaded")
    page.wait_for_timeout(1800)
    page.evaluate("() => window.scrollTo(0, 500)")
    page.wait_for_timeout(400)
    rm = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>/卸载/.test(x.textContent)); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
    out["market_uninstall"] = rm
    if rm:
        page.mouse.click(rm["x"], rm["y"])
        page.wait_for_timeout(600)
        out["confirm_open"] = page.evaluate("() => Boolean(document.querySelector('[aria-label=\"卸载插件？\"]')) || document.querySelectorAll('[role=dialog]').length")
        y0 = page.evaluate("() => Math.round(window.scrollY)")
        page.mouse.move(700, 500)
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(900)
        out["confirm_lock"] = {"y_before": y0, "y_after": page.evaluate("() => Math.round(window.scrollY)")}
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    page.close()
    br.close()

print(json.dumps(out, ensure_ascii=False, indent=2))