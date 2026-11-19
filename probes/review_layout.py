import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8799"
sys.stdout.reconfigure(encoding="utf-8")

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    res = {}
    for w, h in [(390, 844), (1440, 900)]:
        ctx = b.new_context(viewport={"width": w, "height": h})
        page = ctx.new_page()
        page.goto(BASE + "/", wait_until="networkidle"); page.wait_for_timeout(1400)
        res[str(w)] = page.evaluate(""" () => {
          const art = document.querySelector('article');
          const grid = art ? art.parentElement : null;
          const top = art ? Math.round(art.getBoundingClientRect().top) : null;
          const gridLeft = grid ? Math.round(grid.getBoundingClientRect().left) : null;
          const h1 = document.querySelector('h1');
          const body = document.body.innerText;
          const count = (s) => (body.match(new RegExp(s, 'g')) || []).length;
          const card = art;
          const title = card ? card.querySelector('h3') : null;
          const meta = card ? [...card.querySelectorAll('div')].find(d => d.innerText.trim() === '点开详情') : null;
          return {
            firstCardTop: top, gridLeft, vh: innerHeight,
            chromeShare: top ? +(top / innerHeight * 100).toFixed(1) : null,
            h1: h1 ? { size: getComputedStyle(h1).fontSize, text: h1.innerText.trim() } : null,
            count639: count('639'), countAll: count('全部'), countRecent: count('最近采集'),
            cardTitleH: title ? Math.round(title.getBoundingClientRect().height) : null,
            metaH: meta ? Math.round(meta.getBoundingClientRect().height) : null,
            cardW: card ? Math.round(card.getBoundingClientRect().width) : null,
            lineHeight: title ? getComputedStyle(title).lineHeight : null,
            containerW: grid ? Math.round(grid.getBoundingClientRect().width) : null
          };
        } """)
        ctx.close()
    # 容器左边缘对齐：feed / settings / item
    for path, name in [("/", "feed"), ("/settings", "settings"), ("/market", "market")]:
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(BASE + path, wait_until="networkidle"); page.wait_for_timeout(1200)
        res[name + "Left"] = page.evaluate(""" () => {
          const h1 = document.querySelector('h1');
          const main = document.querySelector('main') || document.body.firstElementChild;
          return { h1Left: h1 ? Math.round(h1.getBoundingClientRect().left) : null,
                   mainLeft: main ? Math.round(main.getBoundingClientRect().left) : null };
        } """)
        ctx.close()
    # item 页左边缘（点第一张卡）
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle"); page.wait_for_timeout(1000)
    page.locator("article").first.click(); page.wait_for_timeout(2500)
    res["item"] = page.evaluate(""" () => {
      const h1 = document.querySelector('h1');
      const back = [...document.querySelectorAll('a,button')].find(e => e.innerText.trim() === '返回');
      return { h1Left: h1 ? Math.round(h1.getBoundingClientRect().left) : null,
               h1Size: h1 ? getComputedStyle(h1).fontSize : null,
               backLeft: back ? Math.round(back.getBoundingClientRect().left) : null,
               bodySize: (() => { const p = document.querySelector('article p, .prose p'); return p ? getComputedStyle(p).fontSize : null; })() };
    } """)
    print(json.dumps(res, ensure_ascii=False, indent=1))
    b.close()
