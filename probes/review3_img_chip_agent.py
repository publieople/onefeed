
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
    sizes={}
    def on_resp(r):
        if r.request.resource_type=="image":
            try: sizes[r.url]=len(r.body())
            except Exception: pass
    pg.on("response", on_resp)
    pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]'); pg.wait_for_timeout(2500)
    top=sorted(sizes.items(), key=lambda kv: -kv[1])[:6]
    out["biggest"]=[{"bytes":n,"url":u[:110]} for u,n in top]
    # chip 点击 → 新卡首帧
    pg.evaluate("""() => { window.__t = {}; const grid=document.querySelector('main a[href^="/item/"]'); 
      window.__mo = new MutationObserver(() => { if(!window.__t.first) window.__t.first = performance.now(); });
      window.__mo.observe(document.querySelector('main'), {childList:true, subtree:true}); }""")
    t0 = pg.evaluate("() => performance.now()")
    pg.get_by_role("button", name="B 站", exact=False).first.click()
    try:
        pg.wait_for_function("""() => { const a=document.querySelector('main a[href^="/item/"]'); return a && a.textContent.includes('B'); }""", timeout=8000)
    except Exception: pass
    t1 = pg.evaluate("() => performance.now()")
    out["chip_first_dom_ms"] = round(t1-t0, 1)
    pg.wait_for_timeout(400)
    # 收藏对话框静默期间：不做
    # Agent 静默截图
    pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]'); pg.keyboard.press("/"); pg.wait_for_timeout(600)
    box = pg.locator('[data-agent-surface="sheet"] input[placeholder*="问 OneFeed"]').first
    box.fill("今天 B 站有什么值得看的 AI 内容"); pg.keyboard.press("Enter")
    pg.wait_for_timeout(12000)
    surf = pg.locator('[data-agent-surface="sheet"]').first
    out["silence_snapshot_text"] = surf.inner_text()[:600]
    surf.screenshot(path=str(ROOT/".onefeed"/"shots"/"agent-silence-12s.png"))
    # 等结束，最多 70s
    ended = None
    for i in range(70):
        pg.wait_for_timeout(1000)
        st = pg.evaluate("""() => { const s=document.querySelector('[data-agent-surface="sheet"]'); if(!s) return null;
          return {stop: Boolean([...s.querySelectorAll('button')].find(b=>(b.getAttribute('aria-label')||'').includes('停止'))), n: (s.innerText||'').length}; }""")
        if st and not st["stop"]: ended = i+13; break
    out["agent_total_s"] = ended
    print(json.dumps(out, ensure_ascii=False, indent=1)[:3000])
    b.close()
