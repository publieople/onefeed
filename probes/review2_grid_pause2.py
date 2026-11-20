from __future__ import annotations
import json, os, sys, traceback
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
for k in ("TMP","TEMP","TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

B1 = os.environ.get("ONEFEED_URL","http://127.0.0.1:8799")
B2 = os.environ.get("ONEFEED_URL2","http://127.0.0.1:8801")

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
  let g = card.parentElement;
  while (g && getComputedStyle(g).display !== "grid") g = g.parentElement;
  const cols = g ? getComputedStyle(g).gridTemplateColumns : "";
  return {cols: cols.split(" ").length, cardW: +card.getBoundingClientRect().width.toFixed(1)};
})()"""

def summ(rows, long, key="cardW"):
    vals = [ (r[1].get(key) if isinstance(r[1], dict) else r[1]) for r in rows if r[1] is not None ]
    vals = [v for v in vals if v is not None]
    if len(rows) < 2 or not vals: return {}
    durs = [rows[i][0]-rows[i-1][0] for i in range(1,len(rows))]
    ds = sorted(durs)
    steps = [abs(vals[i]-vals[i-1]) for i in range(1,len(vals))]
    return {"frames": len(rows), "span_ms": round(rows[-1][0]-rows[0][0]),
            "p50": round(ds[len(ds)//2],1), "p95": round(ds[min(len(ds)-1,int(len(ds)*.95))],1),
            "max": round(max(durs),1), "jank": sum(1 for d in durs if d>33.4), "gt60": sum(1 for d in durs if d>60),
            "long_n": len(long), "long_max": round(max(long),1) if long else 0,
            "distinct": len(set(round(v,1) for v in vals)), "max_step": round(max(steps),1) if steps else 0,
            "from": round(vals[0],1), "to": round(vals[-1],1)}

out = {"base1": B1, "base2": B2, "errors": []}
def note(step, fn):
    try: fn()
    except Exception as e:
        out["errors"].append(f"{step}: {type(e).__name__}: {e}")
        print("!!", step, type(e).__name__, e, file=sys.stderr)

with sync_playwright() as pw:
    br = pw.chromium.launch(channel="chrome", headless=True,
        args=["--disable-background-timer-throttling","--disable-renderer-backgrounding","--disable-backgrounding-occluded-windows"])

    def part_a():
        page = br.new_page(viewport={"width":1440,"height":900})
        page.goto(B1, wait_until="domcontentloaded")
        page.wait_for_selector("a[href^='/item/']", timeout=20000); page.wait_for_timeout(1600)
        page.evaluate(SAMPLER)
        def btn(part):
            return page.evaluate("""(part) => { const n=[...document.querySelectorAll('button')].find(b => ((b.getAttribute('title')||'')+(b.getAttribute('aria-label')||'')).includes(part)); if(!n) return null; const r=n.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""", part)
        seq = []
        for _ in range(2):
            for part, op in (("收起 Agent","collapse"), ("展开 Agent","expand")):
                b = btn(part)
                if not b: continue
                page.evaluate("(expr) => window.__probe.start(expr)", GRID)
                page.mouse.click(b["x"], b["y"]); page.wait_for_timeout(750)
                r = page.evaluate("() => window.__probe.stop()")
                cols = [x[1] for x in r["rows"] if x[1]]
                seq.append({"op": op, **summ(r["rows"], r["long"]),
                            "cols_set": sorted({c["cols"] for c in cols}),
                            "grid_seq": [f'{c["cols"]}c/{c["cardW"]}' for c in cols][::max(1,len(cols)//12)]})
                page.wait_for_timeout(450)
        out["left_grid"] = seq

        def part_b():
            page.evaluate("() => window.scrollTo(0, 700)"); page.wait_for_timeout(400)
            y0 = page.evaluate("() => Math.round(window.scrollY)")
            box = page.evaluate("""() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; if(!c) return null; const r=c.getBoundingClientRect(); return {x:r.x+r.width/2,y:Math.min(r.y+r.height-20, 820), top:Math.round(c.scrollTop), max:Math.round(c.scrollHeight-c.clientHeight), h:Math.round(r.height)}; }""")
            out["sidebar_box"] = box
            if not box: return
            page.mouse.move(box["x"], box["y"])
            for _ in range(4):
                page.mouse.wheel(0, 400); page.wait_for_timeout(120)
            page.wait_for_timeout(500)
            st = "() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; return Math.round(c.scrollTop); }"
            out["edge_bottom"] = {"scroll_top": page.evaluate(st), "max": box["max"],
                                  "win_y_before": y0, "win_y_after": page.evaluate("() => Math.round(window.scrollY)")}
            page.evaluate("() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; c.scrollTop=0; }")
            page.mouse.move(box["x"], box["y"]); page.mouse.wheel(0, 300); page.wait_for_timeout(650)
            out["edge_mid"] = {"scroll_top": page.evaluate(st), "win_y": page.evaluate("() => Math.round(window.scrollY)")}
        note("B-edge", part_b)
        note("C-confirm", lambda: part_c(page))
        page.close()

    def part_c(page):
        page.goto(B1 + "/market", wait_until="domcontentloaded"); page.wait_for_timeout(1900)
        un = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='卸载'); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        out["uninstall_btn"] = un
        if not un: return
        page.mouse.click(un["x"], un["y"]); page.wait_for_timeout(600)
        out["confirm_open"] = page.evaluate("() => ({dialogs: document.querySelectorAll('[role=dialog]').length})")
        y0 = page.evaluate("() => Math.round(window.scrollY)")
        page.mouse.move(700, 500); page.mouse.wheel(0, 500); page.wait_for_timeout(500)
        out["confirm_bg_scroll"] = {"y_before": y0, "y_after": page.evaluate("() => Math.round(window.scrollY)")}
        sb = page.evaluate("""() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; if(!c) return null; const r=c.getBoundingClientRect(); return {x:r.x+10,y:r.y+200, top:Math.round(c.scrollTop)}; }""")
        if sb:
            page.mouse.move(sb["x"], sb["y"])
            for _ in range(3):
                page.mouse.wheel(0, 400); page.wait_for_timeout(120)
            page.wait_for_timeout(400)
            out["confirm_sidebar"] = {"before": sb["top"], "after": page.evaluate("() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; return Math.round(c.scrollTop); }")}
        page.keyboard.press("Escape"); page.wait_for_timeout(400)

    def part_d():
        page = br.new_page(viewport={"width":1600,"height":900})
        page.goto(B1, wait_until="domcontentloaded")
        page.wait_for_selector("a[href^='/item/']", timeout=20000); page.wait_for_timeout(1600)
        page.evaluate(SAMPLER)
        rb = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x => ((x.getAttribute('title')||'')+(x.getAttribute('aria-label')||'')).includes('右侧栏')); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2,label:(b.getAttribute('title')||b.getAttribute('aria-label'))}; }""")
        out["right_btn"] = rb
        if rb:
            page.evaluate("(expr) => window.__probe.start(expr)", GRID)
            page.mouse.click(rb["x"], rb["y"]); page.wait_for_timeout(950)
            r = page.evaluate("() => window.__probe.stop()")
            cols = [x[1] for x in r["rows"] if x[1]]
            out["right_open"] = {**summ(r["rows"], r["long"]), "cols_set": sorted({c["cols"] for c in cols}),
                                 "grid_seq": [f'{c["cols"]}c/{c["cardW"]}' for c in cols][::max(1,len(cols)//12)]}
        page.close()

    def part_e():
        page = br.new_page(viewport={"width":1440,"height":900})
        page.goto(B2, wait_until="domcontentloaded")
        page.wait_for_selector("a[href^='/item/']", timeout=20000); page.wait_for_timeout(1300)
        href = page.evaluate("() => { const a=document.querySelector('a[href^=\"/item/\"]'); return a?a.getAttribute('href'):null; }")
        out["b2_first_item"] = href
        if not href: return
        page.goto(B2 + href, wait_until="domcontentloaded"); page.wait_for_timeout(2200)
        tab = page.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='原文'); if(!b) return null; const r=b.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        out["source_tab"] = tab
        if not tab: return
        page.mouse.click(tab["x"], tab["y"]); page.wait_for_timeout(700)
        n = page.evaluate("() => document.querySelectorAll('[data-lb-index]').length")
        out["lb_thumb_count"] = n
        if n < 1: return
        th = page.evaluate("""() => { const els=document.querySelectorAll('[data-lb-index]'); const el=els[Math.min(1,els.length-1)]; const r=el.getBoundingClientRect(); return {x:r.x+r.width/2,y:r.y+r.height/2}; }""")
        page.mouse.click(th["x"], th["y"]); page.wait_for_timeout(800)
        out["lb_open"] = page.evaluate("() => ({dialogs: document.querySelectorAll('[role=dialog]').length})")
        sb = page.evaluate("""() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; if(!c) return null; const r=c.getBoundingClientRect(); return {x:r.x+10,y:r.y+Math.min(200, r.height-30), top:Math.round(c.scrollTop)}; }""")
        out["lb_sidebar_box"] = sb
        st = "() => { const c=[...document.querySelectorAll('[data-smooth-scroll]')].sort((a,b)=>b.clientHeight-a.clientHeight)[0]; return Math.round(c.scrollTop); }"
        if sb:
            page.mouse.move(sb["x"], sb["y"])
            for _ in range(3):
                page.mouse.wheel(0, 400); page.wait_for_timeout(130)
            page.wait_for_timeout(400)
            out["lb_sidebar_open_top"] = page.evaluate(st)
        page.keyboard.press("Escape"); page.wait_for_timeout(600)
        if sb:
            page.mouse.move(sb["x"], sb["y"])
            for _ in range(2):
                page.mouse.wheel(0, 300); page.wait_for_timeout(130)
            page.wait_for_timeout(600)
            out["lb_sidebar_closed_top"] = page.evaluate(st)
        page.close()

    note("A-left", part_a)
    note("D-right", part_d)
    note("E-lightbox", part_e)
    br.close()

print(json.dumps(out, ensure_ascii=False, indent=2))
