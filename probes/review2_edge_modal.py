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

LIST = r"""() => [...document.querySelectorAll('[data-smooth-scroll]')].map((c,i) => {
  const r = c.getBoundingClientRect();
  return {i, cls: c.className.slice(0,60), max: Math.round(c.scrollHeight-c.clientHeight),
          h: Math.round(r.height), y: Math.round(r.y), top: Math.round(c.scrollTop)};
})"""

with sync_playwright() as pw:
    br = pw.chromium.launch(channel="chrome", headless=True,
        args=["--disable-background-timer-throttling","--disable-renderer-backgrounding","--disable-backgrounding-occluded-windows"])

    def a_home():
        page = br.new_page(viewport={"width":1440,"height":900})
        page.goto(B1, wait_until="domcontentloaded")
        page.wait_for_selector("a[href^='/item/']", timeout=20000); page.wait_for_timeout(1600)
        out["home_containers"] = page.evaluate(LIST)
        # 打开右栏（1440 pinned）
        rb = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x => ((x.getAttribute('title')||'')+(x.getAttribute('aria-label')||'')).includes('右侧栏')); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        if rb:
            page.mouse.click(rb["x"], rb["y"]); page.wait_for_timeout(900)
            out["home_containers_with_rail"] = page.evaluate(LIST)
        page.close()

    def b_edge():
        page = br.new_page(viewport={"width":1440,"height":900})
        page.goto(B1, wait_until="domcontentloaded")
        page.wait_for_selector("a[href^='/item/']", timeout=20000); page.wait_for_timeout(1200)
        # 进详情页拿一条条目，再开右栏看 SavedList 是否可滚
        href = page.evaluate("() => document.querySelector('a[href^=\"/item/\"]').getAttribute('href')")
        page.goto(B1 + href, wait_until="domcontentloaded"); page.wait_for_timeout(2000)
        rb = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x => ((x.getAttribute('title')||'')+(x.getAttribute('aria-label')||'')).includes('右侧栏')); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        if rb:
            page.mouse.click(rb["x"], rb["y"]); page.wait_for_timeout(900)
        conts = page.evaluate(LIST)
        out["item_containers"] = conts
        target = next((c for c in conts if c["max"] > 200), None)
        out["edge_target"] = target
        if not target:
            page.close(); return
        box = page.evaluate("""(i) => { const c=document.querySelectorAll('[data-smooth-scroll]')[i]; const r=c.getBoundingClientRect(); return {x:r.x+8, y:r.y+r.height-40, max:Math.round(c.scrollHeight-c.clientHeight)}; }""", target["i"])
        page.evaluate("() => window.scrollTo(0,0)"); page.wait_for_timeout(300)
        page.mouse.move(box["x"], box["y"])
        for _ in range(5):
            page.mouse.wheel(0, 500); page.wait_for_timeout(140)
        page.wait_for_timeout(600)
        st = page.evaluate("""(i) => { const c=document.querySelectorAll('[data-smooth-scroll]')[i]; return {top: Math.round(c.scrollTop), max: Math.round(c.scrollHeight-c.clientHeight)}; }""", target["i"])
        out["edge_bottom"] = {"container": st, "win_y": page.evaluate("() => Math.round(window.scrollY)")}
        # 再滚一次，指针仍在侧栏底部
        page.mouse.wheel(0, 600); page.wait_for_timeout(700)
        out["edge_bottom_again"] = {"top": page.evaluate("(i) => Math.round(document.querySelectorAll('[data-smooth-scroll]')[i].scrollTop)", target["i"]),
                                    "win_y": page.evaluate("() => Math.round(window.scrollY)")}
        # 指针移到正文区再滚，页面应能滚
        page.mouse.move(700, 500); page.mouse.wheel(0, 400); page.wait_for_timeout(600)
        out["main_wheel_win_y"] = page.evaluate("() => Math.round(window.scrollY)")
        page.close()

    def c_settings_confirm():
        page = br.new_page(viewport={"width":1440,"height":900})
        page.goto(B1 + "/settings", wait_until="domcontentloaded"); page.wait_for_timeout(2200)
        # 展开"AI 助手"找清除 key；直接在 DOM 里点击含"清除所有 key"的按钮
        b = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.includes('清除所有 key')); if(!b) return null; b.scrollIntoView({block:'center'}); const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        out["clear_btn"] = b
        if not b: page.close(); return
        page.wait_for_timeout(400)
        page.mouse.click(b["x"], b["y"]); page.wait_for_timeout(600)
        out["settings_confirm"] = page.evaluate("() => ({dialogs: document.querySelectorAll('[role=dialog]').length, y: Math.round(window.scrollY)})")
        y0 = page.evaluate("() => Math.round(window.scrollY)")
        page.mouse.move(720, 500); page.mouse.wheel(0, 600); page.wait_for_timeout(600)
        out["settings_bg_scroll"] = {"y_before": y0, "y_after": page.evaluate("() => Math.round(window.scrollY)")}
        page.keyboard.press("["); page.wait_for_timeout(500)
        out["confirm_hotkey_left"] = page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--shell-left-w').trim()")
        page.keyboard.press("?"); page.wait_for_timeout(500)
        out["confirm_hotkey_help"] = page.evaluate("() => ({dialogs: document.querySelectorAll('[role=dialog]').length, help: [...document.querySelectorAll('[role=dialog]')].some(d=>d.textContent.includes('快捷键'))})")
        page.keyboard.press("Escape"); page.wait_for_timeout(400)
        page.close()

    def d_lightbox_pause():
        page = br.new_page(viewport={"width":1440,"height":900})
        target = "/item/xiaohongshu%3Anote%3A6aefeb59000000001802c758"
        page.goto(B2 + target, wait_until="domcontentloaded"); page.wait_for_timeout(2200)
        cnt = page.evaluate("() => fetch(location.origin + '/api/item/' + encodeURIComponent(location.pathname.split('/item/')[1])).then(r=>r.json()).then(j=>(j.item&&j.item.images||[]).length)")
        out["patched_item_images"] = cnt
        tab = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='原文'); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        out["source_tab"] = tab
        # 详情可能没有 images，注入 detail 需要 route；先看页面自身
        if tab:
            page.mouse.click(tab["x"], tab["y"]); page.wait_for_timeout(700)
            out["lb_thumb_count"] = page.evaluate("() => document.querySelectorAll('[data-lb-index]').length")
        page.close()

    note("A", a_home)
    note("B", b_edge)
    note("C", c_settings_confirm)
    note("D", d_lightbox_pause)
    br.close()
print(json.dumps(out, ensure_ascii=False, indent=2))
