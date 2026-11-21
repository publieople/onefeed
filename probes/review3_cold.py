
"""第三轮：冷启动与首屏资源实测。"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
OUT = ROOT / ".onefeed" / "review3-cold.json"

INIT = r"""
() => {
  const P = window.__perf = {lcp: 0, cls: 0, long: [], paints: {}};
  try {
    new PerformanceObserver(l => { const e = l.getEntries(); P.lcp = e[e.length-1].startTime; })
      .observe({type: 'largest-contentful-paint', buffered: true});
  } catch (e) {}
  try {
    new PerformanceObserver(l => { for (const e of l.getEntries()) if (!e.hadRecentInput) P.cls += e.value; })
      .observe({type: 'layout-shift', buffered: true});
  } catch (e) {}
  try {
    new PerformanceObserver(l => { for (const e of l.getEntries()) P.long.push({start: +e.startTime.toFixed(1), dur: +e.duration.toFixed(1)}); })
      .observe({type: 'longtask', buffered: true});
  } catch (e) {}
}
"""

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page = ctx.new_page()
        page.add_init_script("(" + INIT + ")()")
        cdp = ctx.new_cdp_session(page)
        cdp.send("Network.enable")
        cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
        reqs = []
        page.on("requestfinished", lambda r: reqs.append(r))
        api = []
        def on_resp(r):
            if "/api/" in r.url:
                try:
                    n = len(r.body())
                except Exception:
                    n = None
                api.append({"url": r.url.replace(BASE, ""), "status": r.status, "bytes": n})
        page.on("response", on_resp)

        t0 = time.time()
        page.goto(BASE + "/", wait_until="commit")
        page.wait_for_selector('a[href^="/item/"]', timeout=30000)
        t_card = time.time() - t0
        nav = page.evaluate("""() => {
          const n = performance.getEntriesByType('navigation')[0] || {};
          const paints = {};
          for (const p of performance.getEntriesByType('paint')) paints[p.name] = +p.startTime.toFixed(1);
          return {ttfb: +n.responseStart?.toFixed(1), dcl: +n.domContentLoadedEventEnd?.toFixed(1),
                  load: +n.loadEventEnd?.toFixed(1), transfer: n.transferSize, encoded: n.encodedBodySize,
                  decoded: n.decodedBodySize, paints};
        }""")
        page.wait_for_timeout(2500)
        perf = page.evaluate("() => window.__perf")
        cdp.send("Performance.enable")
        metrics = cdp.send("Performance.getMetrics")
        m = {x["name"]: x["value"] for x in metrics["metrics"]}
        cards = page.evaluate("() => document.querySelectorAll('a[href^=\"/item/\"]').length")
        nodes = page.evaluate("() => document.getElementsByTagName('*').length")
        res = page.evaluate("""() => {
          const out = {count: 0, bytes: 0, byType: {}};
          for (const e of performance.getEntriesByType('resource')) {
            out.count++;
            const b = e.transferSize || e.encodedBodySize || 0;
            out.bytes += b;
            const t = e.initiatorType || 'other';
            out.byType[t] = (out.byType[t] || 0) + b;
          }
          return out;
        }""")
        first_feed = next((a for a in api if a["url"].startswith("/api/feed")), None)
        out = {
            "t_first_card_s": round(t_card, 3), "nav": nav, "lcp": perf["lcp"], "cls": round(perf["cls"], 4),
            "longtasks": perf["long"], "long_total": round(sum(x["dur"] for x in perf["long"]), 1),
            "js_heap_mb": round(m.get("JSHeapUsedSize", 0) / 1048576, 2),
            "task_duration_s": round(m.get("TaskDuration", 0), 3),
            "nodes": nodes, "cards": cards, "resources": res,
            "api": api, "feed_payload_bytes": first_feed["bytes"] if first_feed else None,
            "requests": [(r.url.replace(BASE, ""), r.resource_type) for r in reqs if "/api/" in r.url or r.resource_type in ("script", "stylesheet", "image", "font")][:80],
        }
        print(json.dumps(out, ensure_ascii=False, indent=1))
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        browser.close()

main()