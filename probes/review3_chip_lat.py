
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
    pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]'); pg.wait_for_timeout(600)
    pg.evaluate("""() => {
      const main = document.querySelector('main');
      window.__m = {t0: 0, loading: 0, idle: 0, href0: main.querySelector('a[href^="/item/"]')?.getAttribute('href') || ''};
      const t0 = performance.now(); window.__m.t0 = t0;
      const tick = () => {
        const m = window.__m, txt = main.innerText;
        if (!m.loading && (txt.indexOf('正在按新条件筛') >= 0 || txt.indexOf('正在取内容') >= 0)) m.loading = Math.round(performance.now() - t0);
        const busy = main.querySelector('[aria-busy]')?.getAttribute('aria-busy');
        const href = main.querySelector('a[href^="/item/"]')?.getAttribute('href') || '';
        if (!m.idle && href !== m.href0 && busy === 'false') m.idle = Math.round(performance.now() - t0);
        if (m.idle || performance.now() - t0 > 6000) return;
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    }""")
    el = pg.locator('button[data-value="bilibili"]').first
    bb = el.bounding_box()
    pg.mouse.click(bb["x"]+bb["width"]/2, bb["y"]+bb["height"]/2)
    pg.wait_for_timeout(2500)
    m = pg.evaluate("() => window.__m")
    net = pg.evaluate("""() => performance.getEntriesByType('resource').filter(e=>e.name.includes('/api/feed')).slice(-1).map(e=>({d:Math.round(e.duration), start:Math.round(e.startTime), size:e.transferSize}))""")
    out["chip"] = {"loading_ms": m.get("loading"), "first_new_card_ms": m.get("idle"), "feed_req": net, "search": pg.evaluate("() => location.search")}
    print(json.dumps(out, ensure_ascii=False))
    b.close()
