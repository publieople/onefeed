import json, time
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8791/item/bilibili%3Avideo%3ABV1Fhsg6FEHM"
with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1280, "height": 800}, color_scheme="dark")
    ctx.add_init_script("localStorage.setItem('onefeed.theme','dark')")
    page = ctx.new_page()
    logs, errs, resp = [], [], []
    page.on("console", lambda m: logs.append((m.type, m.text[:200])))
    page.on("pageerror", lambda e: errs.append(str(e)[:300]))
    def on_resp(r):
        if "/detail" in r.url or "/comments" in r.url:
            resp.append((r.status, r.url.split("/api/")[-1][:120], round(time.time(), 2)))
    page.on("response", on_resp)
    t0 = time.time()
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_timeout(22000)
    info = page.evaluate("""() => {
      const h1 = document.querySelector('h1');
      const cs = h1 ? getComputedStyle(h1) : null;
      return {
        theme: document.documentElement.className,
        h1: h1 ? h1.textContent.trim().slice(0,60) : null,
        h1Opacity: cs ? cs.opacity : null,
        h1Color: cs ? cs.color : null,
        h1Anim: cs ? cs.animationName + '/' + cs.animationFillMode + '/' + cs.animationPlayState : null,
        skeleton: document.querySelectorAll('.skeleton').length,
        loadingHint: document.body.innerText.includes('正在取详情'),
        iframe: !!document.querySelector('iframe'),
        bodyLen: document.body.innerText.length,
      };
    }""")
    print("elapsed", round(time.time() - t0, 1))
    print("INFO", json.dumps(info, ensure_ascii=False))
    print("RESP", resp)
    print("ERRS", errs[:5])
    print("LOGS", [l for l in logs if l[0] in ("error", "warning")][:8])
    page.screenshot(path="probes/tmp_detail_dark.png", full_page=False)
    b.close()
