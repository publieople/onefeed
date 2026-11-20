
import os, sys, json, time, base64
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(ROOT/".onefeed"/"tmp")
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAAJUlEQVR4nO3BAQ0AAADCoPdPbQ8HFAAAAAAAAAAAAAAAAAAAAAB4NBMAAAHr3O0yAAAAAElFTkSuQmCC")
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    # A. 灯箱 + 请求日志
    pg = b.new_context(viewport={"width":1440,"height":900}).new_page()
    seen = []
    pg.on("request", lambda r: seen.append(r.url) if "/detail" in r.url else None)
    pg.route("**/detail*", lambda r: r.fulfill(status=200, content_type="application/json",
        body=json.dumps({"supported": True, "detail": {"body": "正文", "images": [{}, {}, {}], "media": None, "stats": {}, "note": None, "comments": []}})))
    pg.route("**/api/media/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    pg.goto("http://127.0.0.1:8799/?p=bilibili", wait_until="load")
    pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(900)
    pg.locator('a[href^="/item/"]').first.click(); pg.wait_for_url("**/item/**", timeout=15000)
    pg.wait_for_timeout(2600)
    print("detail requests:", seen[:3])
    print("lb count:", pg.locator("[data-lb-index]").count(), "imgs:", pg.evaluate("() => document.querySelectorAll('main img').length"))
    n = pg.locator("[data-lb-index]").count()
    if n >= 3:
        pg.locator('[data-lb-index="1"]').click(); pg.wait_for_timeout(700)
        st = pg.evaluate("""() => ({ov: getComputedStyle(document.body).overflow, idx: (document.body.innerText.match(/(\\d+) \\/ (\\d+)/)||[])[0]||null})""")
        print("LIGHTBOX:", st)
        pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(400)
        print("AFTER RIGHT:", pg.evaluate("""() => (document.body.innerText.match(/(\\d+) \\/ (\\d+)/)||[])[0]||null"""))
        pg.keyboard.press("Escape"); pg.wait_for_timeout(600)
        print("AFTER ESC overflow:", pg.evaluate("() => getComputedStyle(document.body).overflow"),
              "focus:", pg.evaluate("() => { const a=document.activeElement; return a && (a.getAttribute('data-lb-index') || a.tagName); }"))

    # B. Agent 时间线
    pg2 = b.new_context(viewport={"width":1440,"height":900}).new_page()
    pg2.goto("http://127.0.0.1:8799/", wait_until="load")
    pg2.wait_for_selector('a[href^="/item/"]', timeout=25000); pg2.wait_for_timeout(1200)
    pg2.keyboard.press("/"); pg2.wait_for_timeout(600)
    comp = pg2.locator('[data-agent-surface="sheet"] input[placeholder*="问 OneFeed"]').first
    comp.wait_for(state="visible", timeout=8000); comp.click()
    pg2.keyboard.type("今天 B 站有什么值得看的 AI 内容")
    t0 = time.perf_counter(); pg2.keyboard.press("Enter")
    marks = []
    last = -1
    for i in range(300):
        s = pg2.evaluate("""() => { const el=document.querySelector('[data-agent-surface="sheet"]'); if(!el) return null;
          return {len: el.innerText.length, hasPlan: el.innerText.includes('打算这么做'), hasResult: el.innerText.includes('条') && el.innerText.includes('总结')}; }""")
        if s is None: break
        if s["len"] != last:
            marks.append((round((time.perf_counter()-t0)*1000), s["len"], s["hasPlan"]))
            last = s["len"]
        if ("打算这么做" in "" ) : pass
        if s["hasResult"] and s["len"] > 300: break
        time.sleep(0.12)
    print("AGENT 文本变化时间线:", marks[:20], "…共", len(marks), "耗时", round((time.perf_counter()-t0)*1000), "ms")
    pg2.keyboard.press("Escape"); pg2.wait_for_timeout(500)

    # C. 停止键
    pg3 = b.new_context(viewport={"width":1440,"height":900}).new_page()
    pg3.goto("http://127.0.0.1:8799/", wait_until="load")
    pg3.wait_for_selector('a[href^="/item/"]', timeout=25000); pg3.wait_for_timeout(1200)
    pg3.keyboard.press("/"); pg3.wait_for_timeout(600)
    c3 = pg3.locator('[data-agent-surface="sheet"] input[placeholder*="问 OneFeed"]').first
    c3.wait_for(state="visible", timeout=8000); c3.click()
    pg3.keyboard.type("找五条 B 站讲大模型的视频，分别总结")
    pg3.keyboard.press("Enter"); pg3.wait_for_timeout(3500)
    stop_info = pg3.evaluate("""() => { const el=document.querySelector('[data-agent-surface="sheet"]');
       const b=[...el.querySelectorAll('button')].filter(x => x.querySelector('svg.lucide-square') || /停止/.test(x.getAttribute('aria-label')||x.title||''));
       return b.map(x => ({t:(x.innerText||'').trim().slice(0,10), aria:x.getAttribute('aria-label'), r:x.getBoundingClientRect().height})); }""")
    print("STOP BUTTONS:", stop_info)
    clicked = pg3.evaluate("""() => { const el=document.querySelector('[data-agent-surface="sheet"]');
       const b=[...el.querySelectorAll('button')].find(x => x.querySelector('svg.lucide-square') || /停止/.test(x.getAttribute('aria-label')||x.title||''));
       if(b){b.click(); return true;} return false; }""")
    print("clicked stop:", clicked)
    pg3.wait_for_timeout(2500)
    after = pg3.evaluate("""() => (document.querySelector('[data-agent-surface="sheet"]')||{}).innerText?.replace(/\s+/g,' ').slice(-160)""")
    print("AFTER STOP:", after)
    pg3.wait_for_timeout(2500)
    print("AFTER STOP+5s:", pg3.evaluate("""() => (document.querySelector('[data-agent-surface="sheet"]')||{}).innerText?.replace(/\s+/g,' ').slice(-120)"""))
    b.close()
