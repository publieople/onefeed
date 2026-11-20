from __future__ import annotations
import gzip, json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
for k in ("TMP","TEMP","TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
B1 = os.environ.get("ONEFEED_URL","http://127.0.0.1:8799")
out = {}

# 包体
dist = sorted((ROOT/"web"/"dist"/"assets").glob("index-*.js"))
if dist:
    raw = dist[-1].read_bytes()
    out["bundle"] = {"file": dist[-1].name, "raw_kb": round(len(raw)/1024,1), "gzip_kb": round(len(gzip.compress(raw,9))/1024,1),
                     "lenis_mentions": raw.count(b"data-lenis-prevent") + raw.count(b"lenis-")}

FRAME = r"""
() => {
  window.__f = { rows: [], long: [], running: false,
    start() { this.rows=[]; this.long=[]; this.running=true;
      const tick=(now)=>{ if(!this.running) return; this.rows.push(now); requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
      this.po=new PerformanceObserver(l=>{for(const e of l.getEntries()) this.long.push(+e.duration.toFixed(1));});
      try{this.po.observe({entryTypes:["longtask"]});}catch(e){}
    },
    stop(){ this.running=false; try{this.po.disconnect();}catch(e){}
      const d=[]; for(let i=1;i<this.rows.length;i++) d.push(this.rows[i]-this.rows[i-1]);
      d.sort((a,b)=>a-b);
      return {frames:this.rows.length, p50:+ (d[Math.floor(d.length/2)]||0).toFixed(1),
              p95:+ (d[Math.min(d.length-1,Math.floor(d.length*0.95))]||0).toFixed(1),
              max:+(d[d.length-1]||0).toFixed(1), jank:d.filter(x=>x>33.4).length,
              gt60:d.filter(x=>x>60).length, long_n:this.long.length, long_max:this.long.length?Math.max(...this.long):0};
    }};
}
"""

with sync_playwright() as pw:
    br = pw.chromium.launch(channel="chrome", headless=True,
        args=["--disable-background-timer-throttling","--disable-renderer-backgrounding","--disable-backgrounding-occluded-windows"])

    # 1) 直接写 scrollTop 是否被 Lenis 拉回
    page = br.new_page(viewport={"width":1440,"height":900})
    page.goto(B1, wait_until="domcontentloaded")
    page.wait_for_selector("a[href^='/item/']", timeout=20000); page.wait_for_timeout(1800)
    out["lenis_instances_home"] = page.evaluate("() => document.querySelectorAll('.lenis').length")
    res = page.evaluate("""() => { const c=document.querySelectorAll('[data-smooth-scroll]')[0];
      const before=c.scrollTop; c.scrollTop=120; return {before:Math.round(before), set:Math.round(c.scrollTop)}; }""")
    page.wait_for_timeout(700)
    res2 = page.evaluate("() => Math.round(document.querySelectorAll('[data-smooth-scroll]')[0].scrollTop)")
    out["direct_write"] = {**res, "after_700ms": res2}
    page.evaluate("""() => { const c=document.querySelectorAll('[data-smooth-scroll]')[0]; c.scrollTo({top: 200, behavior:'instant'}); }""")
    page.wait_for_timeout(700)
    out["direct_write_instant"] = page.evaluate("() => Math.round(document.querySelectorAll('[data-smooth-scroll]')[0].scrollTop)")
    page.close()

    # 2) 详情页开 AI 侧栏后实例数 + 流式期间帧/longtask
    page = br.new_page(viewport={"width":1440,"height":900})
    page.goto(B1, wait_until="domcontentloaded")
    page.wait_for_selector("a[href^='/item/']", timeout=20000); page.wait_for_timeout(1000)
    href = page.evaluate("() => document.querySelector('a[href^=\"/item/\"]').getAttribute('href')")
    page.goto(B1 + href, wait_until="domcontentloaded"); page.wait_for_timeout(2400)
    ai = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x => (x.getAttribute('aria-label')||'')==='打开 AI 助手'); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
    out["ai_btn"] = ai
    if ai:
        page.mouse.click(ai["x"], ai["y"]); page.wait_for_timeout(1200)
        out["lenis_instances_item_ai"] = page.evaluate("() => document.querySelectorAll('.lenis').length")
        composer = page.evaluate("""() => { const s=document.querySelector('[data-agent-surface="sheet"]') || document; const i=[...s.querySelectorAll('input[placeholder*="问 OneFeed"]')].find(x=>x.offsetParent!==null); if(!i) return null; const r=i.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        out["composer"] = composer
        if composer:
            page.mouse.click(composer["x"], composer["y"]); page.wait_for_timeout(300)
            page.keyboard.type("这条讲了什么")
            page.evaluate(FRAME); page.evaluate("() => window.__f.start()")
            page.keyboard.press("Enter")
            page.wait_for_timeout(10000)
            out["stream_frames"] = page.evaluate("() => window.__f.stop()")
            out["stream_text"] = page.evaluate("""() => { const s=document.querySelector('[data-agent-surface="sheet"]') || document.body; return (s.innerText||'').replace(/\s+/g,' ').slice(-160); }""")
    page.close()
    br.close()
print(json.dumps(out, ensure_ascii=False, indent=2))
