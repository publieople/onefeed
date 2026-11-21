
import os, sys, json, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT/".onefeed"/"tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
BASE="http://127.0.0.1:8799"; out={}
with sync_playwright() as p:
    b=p.chromium.launch(channel="chrome", headless=True)
    ctx=b.new_context(viewport={"width":1440,"height":900}); pg=ctx.new_page()
    pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]'); pg.wait_for_timeout(500)

    # A. 返回信息流是否恢复滚动位置
    pg.mouse.wheel(0, 1200); pg.wait_for_timeout(700)
    y0 = pg.evaluate("() => window.scrollY")
    cards = pg.locator('main a[href^="/item/"]')
    # 找视口中间的卡
    idx = pg.evaluate("""() => { const as=[...document.querySelectorAll('main a[href^="/item/"]')]; const i=as.findIndex(a=>{const r=a.getBoundingClientRect(); return r.top>100 && r.top<600;}); return i; }""")
    cards.nth(idx).click()
    pg.wait_for_selector("h1", timeout=15000); pg.wait_for_timeout(500)
    pg.get_by_role("button", name="返回").first.click() if pg.get_by_role("button", name="返回").count() else pg.keyboard.press("Escape")
    pg.wait_for_timeout(1200)
    ys = [pg.evaluate("() => window.scrollY")]
    for _ in range(6):
        pg.wait_for_timeout(250); ys.append(pg.evaluate("() => window.scrollY"))
    out["back_scroll"] = {"before": y0, "after": ys, "cards": pg.locator('main a[href^="/item/"]').count(), "url": pg.evaluate("() => location.pathname + location.search")}

    # B. 收藏对话框打开时滚轮是否穿透
    pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]'); pg.wait_for_timeout(400)
    pg.locator('main a[href^="/item/"]').first.click(); pg.wait_for_selector("h1"); pg.wait_for_timeout(600)
    pg.get_by_role("button", name="收藏", exact=True).first.click()
    pg.wait_for_timeout(400)
    y_before = pg.evaluate("() => window.scrollY")
    has_dialog = pg.locator('[role=dialog]').count()
    pg.mouse.wheel(0, 700); pg.wait_for_timeout(700)
    out["modal_wheel"] = {"dialogs": has_dialog, "y_before": y_before, "y_after": pg.evaluate("() => window.scrollY"),
        "body_overflow": pg.evaluate("() => getComputedStyle(document.body).overflow")}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    b.close()
