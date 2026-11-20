
"""用 CDP trace 看展开那一下的主线程都花在什么事件上。"""
from __future__ import annotations
import collections, json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="load")
    page.wait_for_selector('a[href^="/item/"]', timeout=25000)
    page.wait_for_timeout(1500)
    page.locator('button[title*="收起"], button[aria-label*="收起"]').first.click()
    page.wait_for_timeout(900)

    cdp = ctx.new_cdp_session(page)
    cdp.send("Tracing.start", {"categories": "devtools.timeline,disabled-by-default-devtools.timeline", "transferMode": "ReturnAsStream"})
    page.locator('button[title*="展开"], button[aria-label*="展开"]').first.click()
    page.wait_for_timeout(1200)
    done = {}
    def on_complete(ev):
        done["stream"] = ev.get("stream")
    cdp.on("Tracing.tracingComplete", on_complete)
    cdp.send("Tracing.end")
    for _ in range(100):
        if "stream" in done: break
        page.wait_for_timeout(100)
    stream = done.get("stream")
    chunks = []
    while True:
        r = cdp.send("IO.read", {"handle": stream, "size": 2000000})
        chunks.append(r.get("data", ""))
        if r.get("eof"): break
    raw = "".join(chunks)
    t = json.loads(raw)
    evs = t.get("traceEvents", [])
    dur = collections.Counter()
    counts = collections.Counter()
    for e in evs:
        if e.get("ph") == "X" and e.get("dur"):
            name = e.get("name")
            dur[name] += e["dur"] / 1000.0
            counts[name] += 1
    for name, ms in dur.most_common(14):
        print(f"{ms:9.1f}ms  x{counts[name]:<4} {name}", flush=True)
    b.close()
