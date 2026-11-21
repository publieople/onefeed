"""真机核对：刷新真的会带来新内容、冷却会说清楚、设置里有平台间隔。

跑法：python probes/probe_refresh_live.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("ONEFEED_BASE", "http://127.0.0.1:8799")
OUT = ROOT / "probes" / "out"
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    os.environ.setdefault("TEMP", str(ROOT / ".onefeed" / "tmp" / "pwtemp"))
    os.environ.setdefault("TMP", os.environ["TEMP"])
    report = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        page.goto(BASE + "/", wait_until="domcontentloaded")
        page.wait_for_selector("article", timeout=20000)
        page.wait_for_timeout(800)

        body = page.inner_text("body")
        report["demo_banner"] = "离线演示模式" in body
        report["summary_line"] = next(
            (ln for ln in body.splitlines() if "库里共" in ln), ""
        )
        report["first_cards"] = [
            t.strip() for t in page.locator("article").all_inner_texts()[:3]
        ]

        # 点刷新：冷却中应当直接给「仍要抓」，而不是假装开始
        page.get_by_role("button", name="刷新").click()
        page.wait_for_timeout(1600)
        toast = page.evaluate(
            "() => { const n = document.querySelector('[role=status]'); return n ? n.innerText : '' }"
        )
        report["refresh_toast"] = toast
        report["still_fetch_button"] = page.get_by_role("button", name="仍要抓").count()
        page.screenshot(path=str(OUT / "refresh-cooldown.png"), full_page=False)

        # 设置页：平台抓取间隔
        page.goto(BASE + "/settings", wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        # 「采集与排序」默认收起，间隔输入在折叠面板里
        page.get_by_role("button", name="采集与排序").first.click()
        page.wait_for_timeout(700)
        inputs = page.locator("input[aria-label$='抓取间隔（分钟）']")
        report["interval_inputs"] = inputs.count()
        report["interval_values"] = [inputs.nth(i).input_value() for i in range(inputs.count())]
        report["has_section_text"] = "平台抓取间隔" in page.inner_text("body")
        # 改一个值并存盘，确认 PUT 生效
        if inputs.count():
            target = page.locator("input[aria-label='V2EX 抓取间隔（分钟）']")
            target.fill("7")
            page.get_by_role("button", name="保存").first.click()
            page.wait_for_timeout(1200)
            report["after_save_toast"] = page.evaluate(
                "() => { const n = document.querySelector('[role=status]'); return n ? n.innerText : '' }"
            )
            report["v2ex_saved_value"] = target.input_value()
            target.fill("5")
            page.get_by_role("button", name="保存").first.click()
            page.wait_for_timeout(1000)
        page.screenshot(path=str(OUT / "settings-intervals.png"), full_page=False)
        browser.close()

    text = json.dumps(report, ensure_ascii=False, indent=2)
    (OUT / "refresh-live.json").write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
