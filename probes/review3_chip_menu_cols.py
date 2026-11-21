
import os, sys, json
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
    pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]'); pg.wait_for_timeout(800)

    # A. 胶囊点击 → loading 文案 / 新卡 / 稳定
    pg.evaluate("""() => {
      window.__m = {t0: 0, loading: 0, firstHref: 0, idle: 0};
      const main = document.querySelector('main');
      const t0 = performance.now(); window.__m.t0 = t0;
      const href0 = main.querySelector('a[href^="/item/"]')?.getAttribute('href');
      const tick = () => {
        const m = window.__m;
        if (!m.loading && main.innerText.includes('正在按新条件筛')) m.loading = performance.now() - t0;
        const href = main.querySelector('a[href^="/item/"]')?.getAttribute('href');
        if (!m.firstHref && href && href !== href0) m.firstHref = performance.now() - t0;
        const busy = main.querySelector('[aria-busy]')?.getAttribute('aria-busy');
        if (!m.idle && href !== href0 && busy === 'false') m.idle = performance.now() - t0;
        if (m.idle || performance.now() - t0 > 6000) return;
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }""")
    pg.get_by_role("button", name="B 站", exact=False).first.click()
    pg.wait_for_timeout(3500)
    out["chip"] = pg.evaluate("() => window.__m")

    # B. 卡片菜单焦点
    pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]'); pg.wait_for_timeout(600)
    pg.locator('button[aria-label="更多操作"]').first.click()
    pg.wait_for_timeout(300)
    s1 = pg.evaluate("""() => ({active: document.activeElement?.getAttribute('role') || document.activeElement?.tagName,
        y: document.activeElement?.getBoundingClientRect().top})""")
    pg.keyboard.press("ArrowDown"); pg.wait_for_timeout(200)
    s2 = pg.evaluate("""() => ({active: document.activeElement?.textContent?.trim()?.slice(0,20), y: document.activeElement?.getBoundingClientRect().top})""")
    out["menu"] = {"open": s1, "after_down": s2}
    pg.keyboard.press("Escape")

    # C. 18 卡改列数
    pg.wait_for_timeout(300)
    pg.evaluate("""() => { window.__lt = []; try { new PerformanceObserver(l => { for (const e of l.getEntries()) window.__lt.push(Math.round(e.duration)); }).observe({type:'longtask', buffered:false}); } catch(e){} }""")
    pg.locator('button[title*="每行显示"]').first.click(); pg.wait_for_timeout(400)
    pg.get_by_role("button", name="2 列", exact=False).first.click()
    pg.wait_for_timeout(1200)
    out["cols18"] = pg.evaluate("() => ({long: window.__lt, cards: document.querySelectorAll('a[href^=\"/item/\"]').length, cols: getComputedStyle(document.querySelector('main section[aria-busy]')).gridTemplateColumns.split(' ').length})")
    print(json.dumps(out, ensure_ascii=False, indent=1)[:2500])
    b.close()
