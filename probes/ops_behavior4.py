
import os, sys, json, time, base64
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(ROOT/".onefeed"/"tmp")
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAGQAAABkCAIAAAD/gAIDAAAAJUlEQVR4nO3BAQ0AAADCoPdPbQ8HFAAAAAAAAAAAAAAAAAAAAAB4NBMAAAHr3O0yAAAAAElFTkSuQmCC")
out=[]
def check(n,c,d=""):
    out.append({"name":n,"ok":bool(c),"detail":str(d)[:400]}); print(("PASS " if c else "FAIL ")+n+("  :: "+str(d)[:300] if d else ""), flush=True)

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    # ---- 灯箱：拦截 detail 接口伪造三图 ----
    pg = b.new_context(viewport={"width":1440,"height":900}).new_page()
    ID = "bilibili:bvid:BV1xx411c7mD"
    def detail_route(route):
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "supported": True, "detail": {"body": "正文", "images": [{}, {}, {}], "media": None,
            "stats": {}, "note": None, "comments": []}}))
    pg.route("**/api/item/*/detail*", detail_route)
    pg.route("**/api/media/**", lambda r: r.fulfill(status=200, content_type="image/png", body=PNG))
    pg.goto("http://127.0.0.1:8799/?p=bilibili", wait_until="load")
    pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(900)
    pg.locator('a[href^="/item/"]').first.click(); pg.wait_for_url("**/item/**", timeout=15000)
    pg.wait_for_timeout(2500)
    n = pg.locator("[data-lb-index]").count()
    check("三图详情渲染缩略图", n >= 3, n)
    if n >= 3:
        pg.locator('[data-lb-index="1"]').click()
        pg.wait_for_timeout(700)
        st = pg.evaluate("""() => ({dlg: document.querySelectorAll('[role=dialog]').length,
            ov: getComputedStyle(document.body).overflow,
            idx: (document.body.innerText.match(/(\\d+) \\/ (\\d+)/)||[])[0] || null,
            focusIn: (()=>{const d=[...document.querySelectorAll('div')].find(x=>x.className.includes && String(x.className).includes('z-[60]')); return d?d.contains(document.activeElement):null;})()})""")
        check("灯箱打开（dialog+锁滚动）", st["dlg"]>=1 and st["ov"]=="hidden", st)
        check("灯箱显示当前序号", st["idx"] is not None, st["idx"])
        pg.keyboard.press("ArrowRight"); pg.wait_for_timeout(500)
        st2 = pg.evaluate("""() => (document.body.innerText.match(/(\\d+) \\/ (\\d+)/)||[])[0] || null""")
        check("→ 键切下一张", st2 and st2 != st["idx"], {"before": st["idx"], "after": st2})
        pg.keyboard.press("ArrowLeft"); pg.wait_for_timeout(400)
        pg.keyboard.press("Escape"); pg.wait_for_timeout(700)
        check("Esc 关闭灯箱并解锁滚动", pg.evaluate("() => getComputedStyle(document.body).overflow") != "hidden")
        back = pg.evaluate("""() => { const a=document.activeElement; return a? a.getAttribute('data-lb-index')||a.tagName : 'none'; }""")
        check("关闭后焦点回到缩略图", back not in ("none","BODY"), back)

    # ---- Agent 真实问答 ----
    pg2 = b.new_context(viewport={"width":1440,"height":900}).new_page()
    pg2.goto("http://127.0.0.1:8799/", wait_until="load")
    pg2.wait_for_selector('a[href^="/item/"]', timeout=25000); pg2.wait_for_timeout(1200)
    pg2.keyboard.press("/"); pg2.wait_for_timeout(600)
    comp = pg2.locator('[data-agent-surface="sheet"] input[placeholder*="问 OneFeed"]').first
    comp.wait_for(state="visible", timeout=8000)
    pg2.evaluate("""() => { window.__lt=[]; new PerformanceObserver(l=>{for(const e of l.getEntries()) window.__lt.push(Math.round(e.duration));}).observe({entryTypes:['longtask']}); }""")
    comp.click(); pg2.keyboard.type("找两条 B 站讲 AI 的视频，各写一句总结")
    t0=time.perf_counter(); pg2.keyboard.press("Enter")
    fb=txt=None; samples=[]
    for i in range(220):
        s = pg2.evaluate("""() => { const el=document.querySelector('[data-agent-surface="sheet"]'); if(!el) return {gone:true};
           const t=el.innerText; const stop=!!el.querySelector('svg.lucide-square') || !!el.querySelector('button[aria-label*=停止]');
           return {txt:t, stop, len:t.length}; }""")
        if s.get("gone"): break
        if fb is None and s["stop"]: fb=(time.perf_counter()-t0)*1000
        if txt is None and any(k in s["txt"] for k in ("步","翻","条","要点","听着")): txt=(time.perf_counter()-t0)*1000
        samples.append((round((time.perf_counter()-t0)*1000), s["len"], s["stop"]))
        if ("条。" in s["txt"] or "停下" in s["txt"]) and s["len"]>80: break
        time.sleep(0.15)
    lt = pg2.evaluate("() => window.__lt||[]")
    final = pg2.evaluate("""() => (document.querySelector('[data-agent-surface="sheet"]')||{}).innerText?.replace(/\s+/g,' ').slice(0,300)""")
    check("发送后立即出现停止键", fb is not None, f"{fb and round(fb)}ms")
    check("首屏可见进展", txt is not None, f"{txt and round(txt)}ms")
    check("流式期间长任务可控", len([x for x in lt if x>150])<=3, {"longtasks": lt[:10], "max": max(lt) if lt else 0})
    print("  耗时:", samples[-1][0] if samples else None, "ms  最终:", final[:220], flush=True)
    print("  采样:", samples[:10], "共", len(samples), flush=True)

    # ---- 市场撤销核对 API ----
    pg3 = b.new_context(viewport={"width":1440,"height":900}).new_page()
    pg3.goto("http://127.0.0.1:8799/market", wait_until="load"); pg3.wait_for_timeout(2400)
    def installed():
        return pg3.evaluate("""async () => { const r = await fetch('/api/plugins'); const j = await r.json();
           return (j.installed || []).map(x => x.id || x.name || x); }""")
    i0 = installed()
    pg3.locator('button:has-text("卸载")').first.click(); pg3.wait_for_timeout(600)
    name = pg3.evaluate("""() => (document.querySelector('[role=dialog]')||{}).innerText?.split('？')[0]?.replace('卸载','').trim()""")
    pg3.evaluate("""() => { const d=document.querySelector('[role=dialog]'); const b=[...d.querySelectorAll('button')].find(x=>x.innerText.trim()==='卸载'); b.click(); }""")
    pg3.wait_for_timeout(1200)
    i1 = installed()
    check("卸载后已装数减少", len(i1)==len(i0)-1, {"before":len(i0),"after":len(i1),"removed":name})
    undo_btn = pg3.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='撤销'); if(!b) return null;
        const r=b.getBoundingClientRect(); return {y:Math.round(r.y), w:Math.round(r.width), h:Math.round(r.height)}; }""")
    check("撤销按钮可见且可点", bool(undo_btn and undo_btn["h"]>=20), undo_btn)
    pg3.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='撤销'); if(b) b.click(); }""")
    pg3.wait_for_timeout(1500)
    i2 = installed()
    check("撤销后恢复安装", len(i2)==len(i0), {"after_undo":len(i2),"expect":len(i0)})
    b.close()
ok=sum(1 for r in out if r["ok"])
print(f"\n=== {ok}/{len(out)} ===")
(ROOT/".onefeed"/"ops-behavior4.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
