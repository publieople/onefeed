"""限速冷启动：Fast 3G + 4x CPU，量首卡、LCP、长任务。

对比基线是第三轮评审里的 9.4s 首卡 / 9224ms LCP / 5634ms 长任务（拆包前）。
"""
from __future__ import annotations

import json
import os

from playwright.sync_api import sync_playwright

URL = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799/")

INIT = """
window.__lt = [];
try {
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) window.__lt.push(Math.round(e.duration));
  }).observe({ entryTypes: ['longtask'] });
} catch (e) {}
window.__lcp = 0;
window.__lcpEl = '';
try {
  new PerformanceObserver((list) => {
    const e = list.getEntries().at(-1);
    if (e) {
      window.__lcp = Math.round(e.startTime);
      const el = e.element;
      window.__lcpEl = el ? el.tagName + ' ' + (el.className || '').toString().slice(0, 90) : '';
    }
  }).observe({ type: 'largest-contentful-paint', buffered: true });
} catch (e) {}
"""


def once() -> dict:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.add_init_script(INIT)
        cdp = ctx.new_cdp_session(page)
        if os.environ.get("NO_THROTTLE") != "1":
            cdp.send("Network.enable")
            cdp.send(
                "Network.emulateNetworkConditions",
                {
                    "offline": False,
                    "latency": 150,
                    "downloadThroughput": int(1.6 * 1024 * 1024 / 8),
                    "uploadThroughput": int(750 * 1024 / 8),
                },
            )
            cdp.send("Emulation.setCPUThrottlingRate", {"rate": 4})
        page.goto(URL, wait_until="commit")
        page.wait_for_selector("article", timeout=120000)
        first_card = page.evaluate("() => Math.round(performance.now())")
        page.wait_for_timeout(4000)
        stats = page.evaluate(
            """() => ({
              lcp: Math.round(window.__lcp),
              lcpEl: window.__lcpEl,
              longTasks: window.__lt,
              longTaskTotal: window.__lt.reduce((a, b) => a + b, 0),
              requests: performance.getEntriesByType('resource').length,
              transferred: Math.round(
                performance.getEntriesByType('resource').reduce((a, r) => a + (r.transferSize || 0), 0) / 1024,
              ),
            })"""
        )
        out = {"first_card_ms": first_card, **stats}
        browser.close()
    return out


def main() -> None:
    runs = [once() for _ in range(3)]
    runs.sort(key=lambda r: r["first_card_ms"])
    print(json.dumps({"runs": runs, "median": runs[1]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
