
"""第三轮：长列表滚动 / 累积挂载 / 换筛选的帧数据。"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
OUT = ROOT / ".onefeed" / "review3-scroll.json"

PROBE = r"""
() => {
  if (window.__p) return;
  const P = window.__p = {frames: [], long: [], running: false, t0: 0};
  const rec = t => { if (!P.running) return; P.frames.push(t); requestAnimationFrame(rec); };
  try { new PerformanceObserver(l => { if (!P.running) return; for (const e of l.getEntries()) P.long.push({start: e.startTime, dur: e.duration}); }).observe({type: 'longtask', buffered: false}); } catch (e) {}
  P.start = () => { P.frames = []; P.long = []; P.running = true; P.t0 = performance.now(); requestAnimationFrame(rec); };
  P.stop = () => {
    P.running = false;
    const f = P.frames, d = [];
    for (let i = 1; i < f.length; i++) d.push(f[i] - f[i-1]);
    const s = [...d].sort((a,b)=>a-b), q = p => s.length ? s[Math.min(s.length-1, Math.floor(s.length*p))] : null;
    const span = f.length > 1 ? f[f.length-1] - f[0] : 0;
    return {n: d.length, fps: span > 0 ? +(d.length/(span/1000)).toFixed(1) : null,
      p50: q(.5) && +q(.5).toFixed(1), p95: q(.95) && +q(.95).toFixed(1), max: d.length ? +Math.max(...d).toFixed(1) : null,
      jank33: d.filter(x => x > 33).length,
      longMs: +P.long.filter(l => l.start >= P.t0 - 30).reduce((a,l)=>a+l.dur,0).toFixed(1),
      longMax: P.long.filter(l => l.start >= P.t0 - 30).reduce((m,l)=>Math.max(m,l.dur),0)};
  };
}
"""

def wheel(cdp, delta, n=20, gap=0.022):
    for i in range(n):
        cdp.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": 700, "y": 500, "deltaX": 0, "deltaY": delta})
        time.sleep(gap)

def main():
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(BASE + "/", wait_until="load")
        page.wait_for_selector('a[href^="/item/"]')
        page.wait_for_timeout(1200)
        page.evaluate(PROBE)
        cdp = ctx.new_cdp_session(page)
        count = lambda: page.evaluate("() => document.querySelectorAll('a[href^=\"/item/\"]').length")
        nodes = lambda: page.evaluate("() => document.getElementsByTagName('*').length")
        heap = lambda: page.evaluate("() => performance.memory ? Math.round(performance.memory.usedJSHeapSize/1048576*10)/10 : null")
        out["initial"] = {"cards": count(), "nodes": nodes(), "heap_mb": heap()}

        # 1) 36 张卡时的滚动 bursts
        page.evaluate("() => window.__p.start()")
        wheel(cdp, 480, 18)
        page.wait_for_timeout(900)
        out["scroll_initial"] = page.evaluate("() => window.__p.stop()")

        # 2) 连续滚到底，累积卡片
        t_accum = time.time()
        for i in range(9):
            page.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
            page.wait_for_timeout(1400)
        out["accumulate_s"] = round(time.time() - t_accum, 1)
        out["after_load"] = {"cards": count(), "nodes": nodes(), "heap_mb": heap()}
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(800)

        # 3) 累积后滚动
        page.evaluate("() => window.__p.start()")
        wheel(cdp, 480, 24)
        page.wait_for_timeout(900)
        out["scroll_after"] = page.evaluate("() => window.__p.stop()")

        # 4) 累积后换平台筛选（一次重渲染）
        page.evaluate("() => window.__p.start()")
        page.get_by_role("button", name="B 站", exact=False).first.click()
        page.wait_for_timeout(1500)
        out["filter_after"] = page.evaluate("() => window.__p.stop()")
        out["after_filter"] = {"cards": count(), "nodes": nodes(), "heap_mb": heap()}

        # 5) 累积后改列数（重排）
        try:
            page.evaluate("() => window.__p.start()")
            page.locator('button[title*="每行显示"]').first.click()
            page.wait_for_timeout(250)
            page.get_by_role("button", name="2 列", exact=False).first.click()
            page.wait_for_timeout(1200)
            out["cols_after"] = page.evaluate("() => window.__p.stop()")
        except Exception as e:
            out["cols_after"] = {"error": str(e)[:200]}

        print(json.dumps(out, ensure_ascii=False, indent=1))
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        b.close()

main()