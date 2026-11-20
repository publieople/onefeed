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

TOP = "() => Math.round(document.querySelectorAll('[data-smooth-scroll]')[0].scrollTop)"
RESET = "() => { const c=document.querySelectorAll('[data-smooth-scroll]')[0]; c.scrollTop=0; }"

with sync_playwright() as pw:
    br = pw.chromium.launch(channel="chrome", headless=True,
        args=["--disable-background-timer-throttling","--disable-renderer-backgrounding","--disable-backgrounding-occluded-windows"])

    def a_confirm_pause():
        page = br.new_page(viewport={"width":1440,"height":900})
        page.goto(B1 + "/settings", wait_until="domcontentloaded"); page.wait_for_timeout(2400)
        sb = page.evaluate("""() => { const c=document.querySelectorAll('[data-smooth-scroll]')[0]; const r=c.getBoundingClientRect(); return {x:r.x+8,y:r.y+80, max:Math.round(c.scrollHeight-c.clientHeight)}; }""")
        out["sidebar"] = sb
        page.mouse.move(sb["x"], sb["y"]); page.mouse.wheel(0, 300); page.wait_for_timeout(800)
        out["baseline_top"] = page.evaluate(TOP)
        page.evaluate(RESET); page.wait_for_timeout(900)
        out["reset_top"] = page.evaluate(TOP)
        b = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.includes('清除所有 key')); if(!b) return null; b.scrollIntoView({block:'center'}); const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        page.wait_for_timeout(300); page.mouse.click(b["x"], b["y"]); page.wait_for_timeout(700)
        out["dialog"] = page.evaluate("() => document.querySelectorAll('[role=dialog]').length")
        before = page.evaluate(TOP)
        by = page.evaluate("() => Math.round(scrollY)")
        page.mouse.move(sb["x"], sb["y"])
        for _ in range(3):
            page.mouse.wheel(0, 400); page.wait_for_timeout(140)
        page.wait_for_timeout(700)
        out["dialog_open_wheel"] = {"sidebar_before": before, "sidebar_after": page.evaluate(TOP),
                                    "body_before": by, "body_after": page.evaluate("() => Math.round(scrollY)")}
        page.keyboard.press("Escape"); page.wait_for_timeout(700)
        page.evaluate(RESET); page.wait_for_timeout(900)
        page.mouse.move(sb["x"], sb["y"]); page.mouse.wheel(0, 300); page.wait_for_timeout(800)
        out["after_close_top"] = page.evaluate(TOP)
        page.close()

    def b_lightbox_pause():
        page = br.new_page(viewport={"width":1440,"height":900})
        page.goto(B2 + "/item/xiaohongshu%3Anote%3A6aefeb59000000001802c758", wait_until="domcontentloaded")
        page.wait_for_timeout(2600)
        out["page_metrics"] = page.evaluate("() => ({sh: document.scrollingElement.scrollHeight, ih: innerHeight})")
        tab = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='原文'); if(!b) return null; b.scrollIntoView({block:'center'}); const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        page.wait_for_timeout(300)
        if tab: page.mouse.click(tab["x"], tab["y"]); page.wait_for_timeout(800)
        c = page.evaluate("""() => { const c=document.querySelectorAll('[data-smooth-scroll]')[0]; const r=c.getBoundingClientRect(); return {x:r.x+8,y:r.y+80, max:Math.round(c.scrollHeight-c.clientHeight), top:Math.round(c.scrollTop)}; }""")
        out["sidebar"] = c
        page.mouse.move(c["x"], c["y"]); page.mouse.wheel(0, 300); page.wait_for_timeout(800)
        out["baseline_top"] = page.evaluate(TOP)
        page.evaluate(RESET); page.wait_for_timeout(900)
        out["reset_top"] = page.evaluate(TOP)
        th = page.evaluate("""() => { const el=document.querySelectorAll('[data-lb-index]')[1]; el.scrollIntoView({block:'center'}); const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        page.wait_for_timeout(400); page.mouse.click(th["x"], th["y"]); page.wait_for_timeout(1000)
        out["lb"] = page.evaluate("() => ({dialogs: document.querySelectorAll('[role=dialog]').length, overflow: getComputedStyle(document.body).overflow})")
        before = page.evaluate(TOP); by = page.evaluate("() => Math.round(scrollY)")
        page.mouse.move(c["x"], c["y"])
        for _ in range(3):
            page.mouse.wheel(0, 400); page.wait_for_timeout(140)
        page.wait_for_timeout(700)
        out["lb_open_wheel"] = {"sidebar_before": before, "sidebar_after": page.evaluate(TOP),
                                "body_before": by, "body_after": page.evaluate("() => Math.round(scrollY)")}
        page.keyboard.press("Escape"); page.wait_for_timeout(800)
        page.evaluate(RESET); page.wait_for_timeout(900)
        page.mouse.move(c["x"], c["y"]); page.mouse.wheel(0, 300); page.wait_for_timeout(900)
        out["after_close_top"] = page.evaluate(TOP)
        page.close()

    note("A", a_confirm_pause)
    note("B", b_lightbox_pause)
    br.close()
print(json.dumps(out, ensure_ascii=False, indent=2))
