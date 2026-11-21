
"""第三轮：弱网冷启动 + Agent 一轮的界面静默时长。"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT/".onefeed"/"tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8799"
OUT = ROOT/".onefeed"/"review3-throttle-agent.json"; out = {}

INIT = r"""
() => {
  const P = window.__perf = {lcp: 0, long: []};
  try { new PerformanceObserver(l => { const e = l.getEntries(); P.lcp = e[e.length-1].startTime; }).observe({type:'largest-contentful-paint', buffered:true}); } catch(e){}
  try { new PerformanceObserver(l => { for (const e of l.getEntries()) P.long.push(+e.duration.toFixed(0)); }).observe({type:'longtask', buffered:true}); } catch(e){}
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)

    # A. 弱网 + 4x CPU
    ctx = b.new_context(viewport={"width":1440,"height":900})
    pg = ctx.new_page()
    pg.add_init_script("(" + INIT + ")()")
    cdp = ctx.new_cdp_session(pg)
    cdp.send("Network.enable")
    cdp.send("Network.setCacheDisabled", {"cacheDisabled": True})
    cdp.send("Network.emulateNetworkConditions", {"offline": False, "latency": 150,
        "downloadThroughput": int(1.6*1024*1024/8), "uploadThroughput": int(750*1024/8)})
    cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
    t0 = time.time()
    pg.goto(BASE + "/", wait_until="commit")
    try:
        pg.wait_for_selector('a[href^="/item/"]', timeout=60000)
        t_card = round(time.time() - t0, 2)
    except Exception:
        t_card = None
    pg.wait_for_timeout(1500)
    perf = pg.evaluate("() => window.__perf")
    out["throttle"] = {"t_first_card_s": t_card, "lcp_ms": round(perf["lcp"]),
        "long_tasks": perf["long"], "long_total": sum(perf["long"]),
        "cards": pg.evaluate("() => document.querySelectorAll('a[href^=\"/item/\"]').length")}
    ctx.close()

    # B. Agent 一轮：可见文本变化间隔
    ctx = b.new_context(viewport={"width":1440,"height":900})
    pg = ctx.new_page()
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_selector('a[href^="/item/"]')
    pg.wait_for_timeout(500)
    pg.keyboard.press("/")
    pg.wait_for_timeout(600)
    box = pg.locator('[data-agent-surface="sheet"] input[placeholder*="问 OneFeed"]').first
    box.fill("今天 B 站有什么值得看的 AI 内容")
    pg.keyboard.press("Enter")
    t0 = time.time()
    samples = []
    while time.time() - t0 < 50:
        s = pg.evaluate("""() => {
          const surf = document.querySelector('[data-agent-surface="sheet"]');
          if (!surf) return null;
          const t = surf.innerText || '';
          return {n: t.length, stop: Boolean([...surf.querySelectorAll('button')].find(b => (b.getAttribute('aria-label')||'').includes('停止'))),
                  running: t.includes('下一步') || t.includes('等你选')};
        }""")
        samples.append({"t": round(time.time()-t0, 2), "n": s["n"] if s else 0, "stop": s["stop"] if s else False})
        if s and not s["stop"] and s["n"] > 0 and len(samples) > 20:
            # 停止键消失后再等 2s 收尾
            pg.wait_for_timeout(2000); break
        time.sleep(0.15)
    # 计算静默区间
    gaps = []
    prev = samples[0]
    for cur in samples[1:]:
        if cur["n"] != prev["n"]:
            gaps.append(round(cur["t"] - prev["t"], 2))
            prev = cur
    out["agent"] = {"samples": len(samples), "first_len": samples[0]["n"] if samples else None,
        "max_static_gap_s": max(gaps) if gaps else None,
        "gaps_over_3s": sorted([g for g in gaps if g > 3], reverse=True)[:6],
        "final_len": samples[-1]["n"], "elapsed_s": samples[-1]["t"],
        "timeline": [x for x in samples if x["n"] in (samples[0]["n"], max(s["n"] for s in samples))][:3]}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    b.close()
