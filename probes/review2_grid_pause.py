"""本轮第三轮：栏宽补间期间网格列变化、侧栏到底滚轮归属、弹层暂停侧栏滚动。"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
BASE2 = os.environ.get("ONEFEED_URL2", "http://127.0.0.1:8801")

SAMPLER = r"""
() => {
  window.__probe = {
    rows: [], long: [], running: false,
    start(expr) { this.rows = []; this.long = []; this.running = true;
      const fn = new Function("return (" + expr + ")");
      const tick = (now) => { if (!this.running) return;
        let v = null; try { v = fn(); } catch (e) {}
        this.rows.push([+now.toFixed(1), v]); requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
      this.po = new PerformanceObserver((l) => { for (const e of l.getEntries()) this.long.push(+e.duration.toFixed(1)); });
      try { this.po.observe({ entryTypes: ["longtask"] }); } catch (e) {}
    },
    stop() { this.running = false; try { this.po.disconnect(); } catch (e) {}
      return { rows: this.rows, long: this.long }; }
  };
}
"""

GRID = r"""(() => {
  const card = document.querySelector('a[href^="/item/"]');
  if (!card) return null;
  const grid = card.parentElement && card.parentElement.parentElement;
  let g = card.parentElement;
  while (g && !g.style.gridTemplateColumns && getComputedStyle(g).display !== "grid") g = g.parentElement;
  const cols = g ? getComputedStyle(g).gridTemplateColumns : "";
  const w = card.getBoundingClientRect().width;
  return {cols: cols.split(" ").length, cardW: +w.toFixed(1),
          tpl: cols.split(" ").map(x => Math.round(parseFloat(x))).join(",")};
})()"""

def summarize(rows, long, key=None):
    vals = [(r[1].get(key) if isinstance(r[1], dict) else r[1]) for r in rows if r[1] is not None]
    vals = [v for v in vals if v is not None]
    if len(rows) < 2: return {}
    durs = [rows[i][0]-rows[i-1][0] for i in range(1,len(rows))]
    ds = sorted(durs)
    steps = [abs(vals[i]-vals[i-1]) for i in range(1,len(vals))]
    return {"frames": len(rows), "span_ms": round(rows[-1][0]-rows[0][0]),
            "p50": round(ds[len(ds)//2],1), "p95": round(ds[min(len(ds)-1,int(len(ds)*.95))],1),
            "max": round(max(durs),1), "jank": sum(1 for d in durs if d>33.4), "gt60": sum(1 for d in durs if d>60),
            "long_n": len(long), "long_max": round(max(long),1) if long else 0,
            "distinct": len(set(round(v,1) for v in vals)), "max_step": round(max(steps),1) if steps else 0}

out = {}
with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="chrome", headless=True,
        args=["--disable-background-timer-throttling","--disable-renderer-backgrounding",
              "--disable-backgrounding-occluded-windows"])

    # ---------- A. 1440：左栏补间期间网格列/卡宽变化 ----------
    page = browser.new_page(viewport={"width":1440,"height":900})
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("a[href^='/item/']", timeout=20000)
    page.wait_for_timeout(1500)
    page.evaluate(SAMPLER)

    def btn(part):
        return page.evaluate("""(part) => { const n=[...document.querySelectorAll('button')].find(b => ((b.getAttribute('title')||'')+(b.getAttribute('aria-label')||'')).includes(part)); if(!n) return null; const r=n.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""", part)

    seq = []
    for i in range(2):
        c = btn("收起 Agent")
        if c:
            page.evaluate("(expr) => window.__probe.start(expr)", GRID)
            page.mouse.click(c["x"], c["y"]); page.wait_for_timeout(700)
            r = page.evaluate("() => window.__probe.stop()")
            cols = [x[1] for x in r["rows"] if x[1]]
            seq.append({"op":"collapse", **summarize(r["rows"], r["long"], "cardW"),
                        "grid_seq": [f'{c["cols"]}c/{c["cardW"]}' for c in cols][::max(1,len(cols)//14)],
                        "cols_set": sorted({c["cols"] for c in cols}), "cardW_set": sorted({c["cardW"] for c in cols})})
        e = btn("展开 Agent")
        if e:
            page.evaluate("(expr) => window.__probe.start(expr)", GRID)
            page.mouse.click(e["x"], e["y"]); page.wait_for_timeout(750)
            r = page.evaluate("() => window.__probe.stop()")
            cols = [x[1] for x in r["rows"] if x[1]]
            seq.append({"op":"expand", **summarize(r["rows"], r["long"], "cardW"),
                        "grid_seq": [f'{c["cols"]}c/{c["cardW"]}' for c in cols][::max(1,len(cols)//14)],
                        "cols_set": sorted({c["cols"] for c in cols}), "cardW_set": sorted({c["cardW"] for c in cols})})
        page.wait_for_timeout(400)
    out["left_grid"] = seq

    # ---------- B. 侧栏到底后滚轮归属 ----------
    page.evaluate("() => window.scrollTo(0, 700)"); page.wait_for_timeout(400)
    y0 = page.evaluate("() => window.scrollY")
    box = page.evaluate("""() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; if(!c) return null; const r=c.getBoundingClientRect(); return {x:r.x+r.width/2,y:Math.min(r.y+r.height-20, 800), top:c.scrollTop, max:c.scrollHeight-c.clientHeight}; }""")
    if box:
        page.mouse.move(box["x"], box["y"])
        for _ in range(4):
            page.mouse.wheel(0, 400); page.wait_for_timeout(120)
        page.wait_for_timeout(500)
        out["edge_bottom"] = {"box": box,
            "sidebar_top": page.evaluate("() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; return Math.round(c.scrollTop); }"),
            "win_y_before": y0, "win_y_after": page.evaluate("() => Math.round(window.scrollY)")}
        # 再从顶部往下（未到底）确认侧栏会动
        page.evaluate("() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; c.scrollTop=0; }")
        page.mouse.move(box["x"], box["y"]); page.mouse.wheel(0, 300); page.wait_for_timeout(600)
        out["edge_mid"] = {"sidebar_top": page.evaluate("() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; return Math.round(c.scrollTop); }"),
                           "win_y": page.evaluate("() => Math.round(window.scrollY)")}

    # ---------- C. 确认框打开时的背景滚动 + 侧栏滚动 ----------
    page.goto(BASE + "/market", wait_until="domcontentloaded")
    page.wait_for_timeout(1800)
    page.evaluate(SAMPLER)
    un = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='卸载'); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
    out["uninstall_btn"] = un
    if un:
        page.mouse.click(un["x"], un["y"]); page.wait_for_timeout(600)
        out["confirm_open"] = page.evaluate("() => ({dialogs: document.querySelectorAll('[role=dialog]').length, act: document.activeElement ? (document.activeElement.tagName+':'+(document.activeElement.textContent||'').trim().slice(0,10)) : null})")
        y0 = page.evaluate("() => Math.round(window.scrollY)")
        page.mouse.move(700, 500); page.mouse.wheel(0, 500); page.wait_for_timeout(500)
        out["confirm_bg_scroll"] = {"y_before": y0, "y_after": page.evaluate("() => Math.round(window.scrollY)")}
        # 侧栏滚轮在确认框打开时是否被暂停（pause 生效则不动）
        sb = page.evaluate("""() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; if(!c) return null; const r=c.getBoundingClientRect(); return {x:r.x+10,y:r.y+Math.min(r.height/2,300), top:Math.round(c.scrollTop)}; }""")
        if sb:
            page.mouse.move(sb["x"], sb["y"])
            for _ in range(3):
                page.mouse.wheel(0, 400); page.wait_for_timeout(120)
            page.wait_for_timeout(400)
            out["confirm_sidebar"] = {"before": sb["top"], "after": page.evaluate("() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; return Math.round(c.scrollTop); }")}
        page.keyboard.press("Escape"); page.wait_for_timeout(400)
        page.mouse.move(700, 500); page.mouse.wheel(0, 300); page.wait_for_timeout(500)
        out["confirm_closed_bg"] = page.evaluate("() => Math.round(window.scrollY)")

    page.close()

    # ---------- D. 1600：右栏打开时网格列变化 ----------
    page2 = browser.new_page(viewport={"width":1600,"height":900})
    page2.goto(BASE, wait_until="domcontentloaded")
    page2.wait_for_selector("a[href^='/item/']", timeout=20000)
    page2.wait_for_timeout(1500)
    page2.evaluate(SAMPLER)
    rb = page2.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x => ((x.getAttribute('title')||'')+(x.getAttribute('aria-label')||'')).includes('右侧栏')); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2,label:(b.getAttribute('title')||b.getAttribute('aria-label'))}; }""")
    out["right_btn"] = rb
    if rb:
        page2.evaluate("(expr) => window.__probe.start(expr)", GRID)
        page2.mouse.click(rb["x"], rb["y"]); page2.wait_for_timeout(900)
        r = page2.evaluate("() => window.__probe.stop()")
        cols = [x[1] for x in r["rows"] if x[1]]
        out["right_open"] = {**summarize(r["rows"], r["long"], "cardW"),
            "grid_seq": [f'{c["cols"]}c/{c["cardW"]}' for c in cols][::max(1,len(cols)//14)],
            "cols_set": sorted({c["cols"] for c in cols}), "cardW_set": sorted({c["cardW"] for c in cols})}
    page2.close()

    # ---------- E. 8801：灯箱打开时侧栏滚轮应暂停 ----------
    page3 = browser.new_page(viewport={"width":1440,"height":900})
    page3.goto(BASE2, wait_until="domcontentloaded")
    page3.wait_for_selector("a[href^='/item/']", timeout=20000)
    page3.wait_for_timeout(1200)
    item = page3.evaluate("""() => { const a=document.querySelector('a[href^="/item/"]'); return a?a.getAttribute('href'):null; }""")
    page3.goto(BASE2 + item, wait_until="domcontentloaded")
    page3.wait_for_timeout(2000)
    tab = page3.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='原文'); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
    out["source_tab"] = tab
    if tab:
        page3.mouse.click(tab["x"], tab["y"]); page3.wait_for_timeout(700)
        n = page3.evaluate("() => document.querySelectorAll('[data-lb-index]').length")
        out["lb_thumb_count"] = n
        if n:
            th = page3.evaluate("""() => { const el=document.querySelectorAll('[data-lb-index]')[1]; const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
            page3.mouse.click(th["x"], th["y"]); page3.wait_for_timeout(700)
            out["lb_open"] = page3.evaluate("() => ({dialogs: document.querySelectorAll('[role=dialog]').length, overflow: getComputedStyle(document.body).overflow})")
            sb = page3.evaluate("""() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; if(!c) return null; const r=c.getBoundingClientRect(); return {x:r.x+10,y:r.y+200, top:Math.round(c.scrollTop), h:r.height}; }""")
            out["lb_sidebar_box"] = sb
            if sb:
                page3.mouse.move(sb["x"], sb["y"])
                for _ in range(3):
                    page3.mouse.wheel(0, 400); page3.wait_for_timeout(120)
                page3.wait_for_timeout(400)
                out["lb_sidebar_paused_top"] = page3.evaluate("() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; return Math.round(c.scrollTop); }")
            page3.keyboard.press("Escape"); page3.wait_for_timeout(500)
            page3.mouse.move(sb["x"], sb["y"] if sb else 300) if sb else None
            if sb:
                for _ in range(2):
                    page3.mouse.wheel(0, 300); page3.wait_for_timeout(120)
                page3.wait_for_timeout(500)
                out["lb_sidebar_after_close_top"] = page3.evaluate("() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; return Math.round(c.scrollTop); }")
    page3.close()
    browser.close()

print(json.dumps(out, ensure_ascii=False, indent=2))
