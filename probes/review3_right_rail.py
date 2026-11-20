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
SAMPLER = r"""
() => {
  window.__p = { rows: [], long: [], on: false,
    start() { this.rows = []; this.long = []; this.on = true;
      const tick = (now) => { if (!this.on) return;
        const main = document.getElementById('main');
        const card = document.querySelector('a[href^="/item/"]');
        this.rows.push([+now.toFixed(1), main ? +main.getBoundingClientRect().width.toFixed(1) : null,
                        card ? +card.getBoundingClientRect().width.toFixed(1) : null]);
        requestAnimationFrame(tick); };
      requestAnimationFrame(tick);
      this.po = new PerformanceObserver(l => { for (const e of l.getEntries()) this.long.push(+e.duration.toFixed(1)); });
      try { this.po.observe({ entryTypes: ['longtask'] }); } catch (e) {}
    },
    stop() { this.on = false; try { this.po.disconnect(); } catch (e) {}
      const durs = []; for (let i = 1; i < this.rows.length; i++) durs.push(this.rows[i][0] - this.rows[i-1][0]);
      const ds = [...durs].sort((a,b)=>a-b);
      const mains = this.rows.map(r => r[1]).filter(v => v !== null);
      const cards = this.rows.map(r => r[2]).filter(v => v !== null);
      return { frames: this.rows.length, span: Math.round(this.rows[this.rows.length-1][0]-this.rows[0][0]),
               p50: +ds[Math.floor(ds.length/2)].toFixed(1), p95: +ds[Math.min(ds.length-1, Math.floor(ds.length*0.95))].toFixed(1),
               max: +Math.max(...ds).toFixed(1), jank: durs.filter(d=>d>33.4).length, gt60: durs.filter(d=>d>60).length,
               long_n: this.long.length, long_max: this.long.length ? Math.max(...this.long) : 0,
               main_from: mains[0], main_to: mains[mains.length-1], main_distinct: new Set(mains).size,
               card_distinct: new Set(cards).size };
    }};
}
"""
out = {}
with sync_playwright() as pw:
    br = pw.chromium.launch(channel="chrome", headless=True,
        args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding",
              "--disable-backgrounding-occluded-windows"])
    page = br.new_page(viewport={"width": 1440, "height": 900})
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_selector("a[href^='/item/']", timeout=20000)
    page.wait_for_timeout(2000)
    page.evaluate(SAMPLER)
    runs = []
    for i in range(3):
        page.keyboard.press("]")
        page.evaluate("() => window.__p.start()")
        page.wait_for_timeout(700)
        runs.append({"op": "open", **page.evaluate("() => window.__p.stop()")})
        page.wait_for_timeout(400)
        page.keyboard.press("]")
        page.evaluate("() => window.__p.start()")
        page.wait_for_timeout(700)
        runs.append({"op": "close", **page.evaluate("() => window.__p.stop()")})
        page.wait_for_timeout(400)
    out["runs"] = runs
    out["rail"] = page.evaluate("() => { const a=document.querySelector('[data-rail=\"slot\"]'); return a ? Math.round(a.getBoundingClientRect().width) : null; }")
    page.close(); br.close()
print(json.dumps(out, ensure_ascii=False, indent=2))
