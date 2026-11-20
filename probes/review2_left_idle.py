"""本轮第二轮：左栏补间帧、Lenis 空闲 rAF 成本、侧栏到底后的滚轮归属。"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")

SAMPLER = r"""
() => {
  window.__probe = {
    rows: [], long: [], running: false,
    start(expr) { this.rows = []; this.long = []; this.running = true;
      const fn = new Function("return (" + expr + ")");
      let last = performance.now();
      const tick = (now) => { if (!this.running) return;
        let v = null; try { v = fn(); } catch (e) {}
        this.rows.push([+now.toFixed(1), v]);
        this.rows.push;
        last = now; requestAnimationFrame(tick); };
      last = performance.now(); requestAnimationFrame(tick);
      this.po = new PerformanceObserver((l) => { for (const e of l.getEntries()) this.long.push(+e.duration.toFixed(1)); });
      try { this.po.observe({ entryTypes: ["longtask"] }); } catch (e) {}
    },
    stop() { this.running = false; try { this.po.disconnect(); } catch (e) {}
      return { rows: this.rows, long: this.long }; }
  };
  window.__raf = 0;
  if (!window.__rafPatched) {
    window.__rafPatched = true;
    const orig = window.requestAnimationFrame.bind(window);
    window.requestAnimationFrame = (cb) => { window.__raf++; return orig(cb); };
  }
}
"""

def summarize(rows, long):
    vals = [r[1] for r in rows if r[1] is not None]
    if len(rows) < 2:
        return {}
    durs = [rows[i][0] - rows[i-1][0] for i in range(1, len(rows))]
    durs_sorted = sorted(durs)
    p50 = durs_sorted[len(durs_sorted)//2]
    p95 = durs_sorted[min(len(durs_sorted)-1, int(len(durs_sorted)*0.95))]
    steps = [abs(vals[i]-vals[i-1]) for i in range(1, len(vals))]
    return {
      "frames": len(rows), "span_ms": round(rows[-1][0]-rows[0][0]),
      "from": round(vals[0],1) if vals else None, "to": round(vals[-1],1) if vals else None,
      "distinct": len(set(round(v,1) for v in vals)),
      "max_step": round(max(steps),1) if steps else 0,
      "p50": round(p50,1), "p95": round(p95,1), "max": round(max(durs),1),
      "jank": sum(1 for d in durs if d > 33.4), "gt60": sum(1 for d in durs if d > 60),
      "long_n": len(long), "long_max": round(max(long),1) if long else 0, "long_sum": round(sum(long),1),
    }

out = {"base": BASE}
with sync_playwright() as pw:
    browser = pw.chromium.launch(channel="chrome", headless=True,
        args=["--disable-background-timer-throttling","--disable-renderer-backgrounding",
              "--disable-backgrounding-occluded-windows","--window-size=1440,900"])
    page = browser.new_page(viewport={"width":1440,"height":900})
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("a[href^='/item/']", timeout=20000)
    page.wait_for_timeout(1500)
    page.evaluate(SAMPLER)

    cdp = page.context.new_cdp_session(page)
    cdp.send("Performance.enable")

    def task_duration():
        m = {x["name"]: x["value"] for x in cdp.send("Performance.getMetrics")["metrics"]}
        return m.get("TaskDuration", 0)

    def find_btn(label_part):
        return page.evaluate("""(part) => {
          const nodes = [...document.querySelectorAll('button')];
          const hit = nodes.find(n => (n.getAttribute('title')||'').includes(part) || (n.getAttribute('aria-label')||'').includes(part));
          if (!hit) return null;
          const r = hit.getBoundingClientRect();
          return {x: r.x + r.width/2, y: r.y + r.height/2, w: r.width, h: r.height};
        }""", label_part)

    coll = find_btn("收起 Agent")
    out["collapse_btn"] = coll
    expt = find_btn("展开 Agent")
    out["expand_btn"] = expt

    LEFT = "(() => { const el=document.querySelector('[data-shell-left]'); return el?el.getBoundingClientRect().width:0; })()"

    runs = []
    for i in range(3):
        if coll:
            page.evaluate("(expr) => window.__probe.start(expr)", LEFT)
            page.mouse.click(coll["x"], coll["y"])
            page.wait_for_timeout(650)
            r = page.evaluate("() => window.__probe.stop()")
            runs.append({"op":"collapse", **summarize(r["rows"], r["long"])})
            page.wait_for_timeout(500)
        e = find_btn("展开 Agent")
        if e:
            page.evaluate("(expr) => window.__probe.start(expr)", LEFT)
            page.mouse.click(e["x"], e["y"])
            page.wait_for_timeout(700)
            r = page.evaluate("() => window.__probe.stop()")
            runs.append({"op":"expand", **summarize(r["rows"], r["long"])})
            page.wait_for_timeout(500)
    out["left_runs"] = runs

    # ---- 空闲成本 A/B：有 Lenis（默认）vs reduce（shouldSkip 不建实例）----
    page.wait_for_timeout(800)
    raf0 = page.evaluate("() => window.__raf")
    t0 = task_duration(); w0 = time.time()
    page.wait_for_timeout(3000)
    t1 = task_duration(); el = time.time()-w0
    raf1 = page.evaluate("() => window.__raf")
    out["idle_lenis_on"] = {"cpu_ms": round((t1-t0)*1000), "wall_ms": round(el*1000),
                            "cpu_pct": round((t1-t0)/el*100,1), "raf_cb": raf1-raf0,
                            "raf_per_s": round((raf1-raf0)/el)}
    out["lenis_instances"] = page.evaluate("document.querySelectorAll('.lenis').length")

    page.emulate_media(reduced_motion="reduce")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_selector("a[href^='/item/']", timeout=20000)
    page.wait_for_timeout(1500)
    page.evaluate(SAMPLER)
    cdp2 = page.context.new_cdp_session(page)
    cdp2.send("Performance.enable")
    def td2():
        m = {x["name"]: x["value"] for x in cdp2.send("Performance.getMetrics")["metrics"]}
        return m.get("TaskDuration", 0)
    page.wait_for_timeout(600)
    raf0 = page.evaluate("() => window.__raf")
    t0 = td2(); w0 = time.time()
    page.wait_for_timeout(3000)
    t1 = td2(); el = time.time()-w0
    raf1 = page.evaluate("() => window.__raf")
    out["idle_lenis_off"] = {"cpu_ms": round((t1-t0)*1000), "wall_ms": round(el*1000),
                             "cpu_pct": round((t1-t0)/el*100,1), "raf_cb": raf1-raf0,
                             "raf_per_s": round((raf1-raf0)/el)}
    out["lenis_instances_reduce"] = page.evaluate("document.querySelectorAll('.lenis').length")

    # ---- reduce 下左栏收放是否一帧到位 ----
    page.emulate_media(reduced_motion="no-preference")
    browser.close()

print(json.dumps(out, ensure_ascii=False, indent=2))
