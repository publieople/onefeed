from __future__ import annotations
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
for k in ("TMP","TEMP","TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

B1 = os.environ.get("ONEFEED_URL","http://127.0.0.1:8799")
B2 = os.environ.get("ONEFEED_URL2","http://127.0.0.1:8801")
out = {"errors": []}
def note(s, fn):
    try: fn()
    except Exception as e:
        import traceback; out["errors"].append(f"{s}: {type(e).__name__}: {e}"); traceback.print_exc()

with sync_playwright() as pw:
    br = pw.chromium.launch(channel="chrome", headless=True,
        args=["--disable-background-timer-throttling","--disable-renderer-backgrounding","--disable-backgrounding-occluded-windows"])

    def a_item_scroll():
        page = br.new_page(viewport={"width":1440,"height":900})
        page.goto(B1, wait_until="domcontentloaded")
        page.wait_for_selector("a[href^='/item/']", timeout=20000); page.wait_for_timeout(1000)
        href = page.evaluate("() => document.querySelector('a[href^=\"/item/\"]').getAttribute('href')")
        page.goto(B1 + href, wait_until="domcontentloaded"); page.wait_for_timeout(2200)
        out["item_metrics"] = page.evaluate("() => ({sh: document.scrollingElement.scrollHeight, ih: innerHeight, y: Math.round(scrollY)})")
        page.mouse.move(700, 500)
        for _ in range(2):
            page.mouse.wheel(0, 400); page.wait_for_timeout(200)
        page.wait_for_timeout(700)
        out["item_wheel_main"] = page.evaluate("() => Math.round(scrollY)")
        page.close()

    def b_home_main_wheel():
        page = br.new_page(viewport={"width":1440,"height":900})
        page.goto(B1, wait_until="domcontentloaded")
        page.wait_for_selector("a[href^='/item/']", timeout=20000); page.wait_for_timeout(1600)
        out["home_metrics"] = page.evaluate("() => ({sh: document.scrollingElement.scrollHeight, ih: innerHeight})")
        page.mouse.move(700, 500); page.mouse.wheel(0, 400); page.wait_for_timeout(700)
        out["home_wheel_main"] = page.evaluate("() => Math.round(scrollY)")
        # 侧栏到底后再滚，指针停侧栏
        box = page.evaluate("""() => { const c=document.querySelectorAll('[data-smooth-scroll]')[0]; const r=c.getBoundingClientRect(); return {x:r.x+8, y:r.y+r.height-40}; }""")
        page.evaluate("() => window.scrollTo(0,0)"); page.wait_for_timeout(300)
        page.mouse.move(box["x"], box["y"])
        for _ in range(5):
            page.mouse.wheel(0, 500); page.wait_for_timeout(140)
        page.wait_for_timeout(600)
        before = page.evaluate("() => Math.round(scrollY)")
        page.mouse.wheel(0, 600); page.wait_for_timeout(800)
        out["home_sidebar_edge"] = {"win_y": before, "win_y_after": page.evaluate("() => Math.round(scrollY)"),
                                    "sidebar_top": page.evaluate("() => Math.round(document.querySelectorAll('[data-smooth-scroll]')[0].scrollTop)")}
        page.close()

    def c_lightbox_pause():
        page = br.new_page(viewport={"width":1440,"height":900})
        target = "/item/xiaohongshu%3Anote%3A6aefeb59000000001802c758"
        page.goto(B2 + target, wait_until="domcontentloaded"); page.wait_for_timeout(2400)
        tab = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='原文'); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        page.mouse.click(tab["x"], tab["y"]); page.wait_for_timeout(800)
        n = page.evaluate("() => document.querySelectorAll('[data-lb-index]').length")
        out["thumbs"] = n
        sb = page.evaluate("""() => { const c=document.querySelectorAll('[data-smooth-scroll]')[0]; const r=c.getBoundingClientRect(); return {x:r.x+8, y:r.y+60, top:Math.round(c.scrollTop), max:Math.round(c.scrollHeight-c.clientHeight)}; }""")
        out["sidebar"] = sb
        # 先验证灯箱关闭时侧栏可滚
        page.mouse.move(sb["x"], sb["y"]); page.mouse.wheel(0, 300); page.wait_for_timeout(700)
        out["pre_open_sidebar_top"] = page.evaluate("() => Math.round(document.querySelectorAll('[data-smooth-scroll]')[0].scrollTop)")
        page.evaluate("() => { document.querySelectorAll('[data-smooth-scroll]')[0].scrollTop = 0; }"); page.wait_for_timeout(300)
        th = page.evaluate("""() => { const el=document.querySelectorAll('[data-lb-index]')[1]; const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        page.mouse.click(th["x"], th["y"]); page.wait_for_timeout(900)
        out["lb_state"] = page.evaluate("() => ({dialogs: document.querySelectorAll('[role=dialog]').length, bodyOverflow: getComputedStyle(document.body).overflow, y: Math.round(scrollY)})")
        page.mouse.move(sb["x"], sb["y"])
        for _ in range(3):
            page.mouse.wheel(0, 400); page.wait_for_timeout(130)
        page.wait_for_timeout(600)
        out["lb_sidebar_top"] = page.evaluate("() => Math.round(document.querySelectorAll('[data-smooth-scroll]')[0].scrollTop)")
        out["lb_body_y"] = page.evaluate("() => Math.round(scrollY)")
        page.keyboard.press("Escape"); page.wait_for_timeout(700)
        page.mouse.move(sb["x"], sb["y"]); page.mouse.wheel(0, 300); page.wait_for_timeout(800)
        out["after_close_sidebar_top"] = page.evaluate("() => Math.round(document.querySelectorAll('[data-smooth-scroll]')[0].scrollTop)")
        page.close()

    note("A", a_item_scroll)
    note("B", b_home_main_wheel)
    note("C", c_lightbox_pause)
    br.close()
print(json.dumps(out, ensure_ascii=False, indent=2))
