
import os, sys, json
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(ROOT/".onefeed"/"tmp")
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
BASE="http://127.0.0.1:8799"
HELP = """() => { const t=document.body.innerText; return {help: t.includes('快捷键') && t.includes('平台胶囊'), dialogs: document.querySelectorAll('[role=dialog]').length,
   leftW: (()=>{const e=document.querySelector('[style*="--shell-left-w"]'); return getComputedStyle(document.documentElement).getPropertyValue('--shell-left-w').trim();})() }; }"""
with sync_playwright() as p:
    b=p.chromium.launch(channel="chrome", headless=True)
    pg=b.new_context(viewport={"width":1440,"height":900}).new_page()

    # 1. 确认框（无输入）热键隔离
    pg.goto(BASE+"/market", wait_until="load"); pg.wait_for_timeout(2200)
    pg.locator('button:has-text("卸载")').first.click(); pg.wait_for_timeout(700)
    d0 = pg.evaluate("() => document.querySelectorAll('[role=dialog]').length")
    pg.keyboard.press("?"); pg.wait_for_timeout(700)
    s1 = pg.evaluate(HELP)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(400)
    pg.keyboard.press("["); pg.wait_for_timeout(700)
    s2 = pg.evaluate(HELP)
    print("确认框:", d0, "按? 后:", s1, "按[ 后:", s2)
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

    # 2. 星标代价 vs 卡片数量
    def measure_star(query, label):
        pg.goto(BASE + query, wait_until="load")
        pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(1500)
        info = pg.evaluate("""() => ({cards: document.querySelectorAll('a[href^="/item/"]').length})""")
        pg.evaluate("""() => { window.__fr=[]; window.__lt=[]; let last=performance.now(); const loop=(t)=>{ window.__fr.push(t-last); last=t; if (window.__on) requestAnimationFrame(loop); }; window.__on=true; requestAnimationFrame(loop);
           new PerformanceObserver(l=>{for(const e of l.getEntries()) window.__lt.push(Math.round(e.duration));}).observe({entryTypes:['longtask']}); }""")
        pg.locator('button[aria-label="稍后再看"]').first.click()
        pg.wait_for_timeout(900)
        r = pg.evaluate("""() => { const f=window.__fr.slice(2); const s=[...f].sort((a,b)=>a-b);
           window.__on=false; return {n:f.length, max:Math.round(Math.max(...f)), p95:Math.round(s[Math.floor(s.length*0.95)]||0), jank:f.filter(x=>x>33).length, lt:window.__lt}; }""")
        print(f"星标 [{label}] cards={info['cards']} frames={r['n']} max={r['max']} p95={r['p95']} jank={r['jank']} long={r['lt']}")
        return r
    r30 = measure_star("/?p=bilibili", "30 卡")
    r6 = measure_star("/?p=v2ex", "若干卡")
    # 取消收藏，避免污染
    b.close()
