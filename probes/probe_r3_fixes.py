"""第三轮评审 P1 三条的回归探针。

1) C-03 详情页拆包：首屏不下 ItemPage chunk；悬停预热；点击后模块已就位才开始转场。
2) C-01 收藏对话框压热键栈：对话框开着时 [ / t / ? 都不许打到背后的页面。
3) I-01 Agent 心跳：从第一秒起可见文本就要每秒在变，不能十几秒一字不动。
4) C-04 卡片语义：article + 铺满链接，不再有 a > button。
"""
from __future__ import annotations

import json
import os
import re
import time

from playwright.sync_api import sync_playwright

URL = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799/")


def main() -> None:
    report: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            args=["--disable-background-timer-throttling", "--disable-renderer-backgrounding"],
        )
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        chunks: list[str] = []
        page.on("request", lambda r: chunks.append(r.url) if "/assets/" in r.url else None)

        # ---- 1. 拆包：首屏不该有 ItemPage chunk ----
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("[data-vt-grid], main .grid")
        page.wait_for_timeout(800)
        item_chunks_before = [u for u in chunks if "ItemPage" in u]

        # 挑一张带媒体的卡：无媒体条目本来就没有 of-media 可共享，测它会误判
        card = page.locator('article:has([data-vt="media"]):has-text("视频")').first
        card_label = " ".join(card.inner_text().split())[:40]
        card.hover()
        page.wait_for_timeout(400)
        item_chunks_hover = [u for u in chunks if "ItemPage" in u and u not in item_chunks_before]

        card.click()
        page.wait_for_url(re.compile(r"/item/"))
        # 进页面 120ms 内就该有真正的详情内容（媒体/标题共享元素），不能是 Suspense 骨架
        page.wait_for_timeout(120)
        early = page.evaluate(
            """() => ({
              media: !!document.querySelector('[data-vt="media"]'),
              title: !!document.querySelector('[data-vt="title"]'),
              h1: !!document.querySelector('h1'),
              fallback: document.querySelectorAll('main > .pt-10').length,
              skeleton: document.querySelectorAll('.animate-pulse').length,
            })"""
        )
        report["split"] = {
            "clicked_card": card_label,
            "item_chunk_at_first_paint": item_chunks_before,
            "item_chunk_after_hover": item_chunks_hover,
            "detail_dom_120ms": early,
            "ok": not item_chunks_before
            and bool(item_chunks_hover)
            and early["media"]
            and early["title"]
            and early["h1"]
            and early["fallback"] == 0,
        }

        # ---- 2. 收藏对话框压热键栈 ----
        page.wait_for_timeout(600)
        left_before = page.evaluate(
            "() => (document.querySelector('[data-shell-left]')?.getBoundingClientRect().width) || 0"
        )
        theme_before = page.evaluate("() => document.documentElement.classList.contains('dark')")
        dialog_before = page.evaluate("() => document.querySelectorAll('[role=\"dialog\"]').length")

        fav = page.get_by_role("button", name="收藏", exact=True)
        if fav.count() == 0:
            fav = page.get_by_role("button", name="已收藏", exact=True)
        fav.first.click()
        page.wait_for_selector('[role="dialog"]')
        page.wait_for_timeout(200)

        page.keyboard.press("[")
        page.wait_for_timeout(400)
        left_after = page.evaluate(
            "() => (document.querySelector('[data-shell-left]')?.getBoundingClientRect().width) || 0"
        )
        page.keyboard.press("t")
        page.wait_for_timeout(300)
        theme_after = page.evaluate("() => document.documentElement.classList.contains('dark')")
        page.keyboard.press("?")
        page.wait_for_timeout(300)
        dialogs_after = page.evaluate("() => document.querySelectorAll('[role=\"dialog\"]').length")
        report["favorite_scope"] = {
            "dialogs_before": dialog_before,
            "left_before": left_before,
            "left_after_bracket": left_after,
            "theme_before": theme_before,
            "theme_after_t": theme_after,
            "dialogs_after_question": dialogs_after,
            "ok": left_before == left_after and theme_before == theme_after and dialogs_after == 1,
        }
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)

        # ---- 4. 卡片语义（回信息流看） ----
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector("article")
        page.wait_for_timeout(700)
        sem = page.evaluate(
            """() => {
              const cards = Array.from(document.querySelectorAll('article'));
              const nested = cards.filter((c) => c.querySelector('a button, button a')).length;
              const links = cards.filter((c) => c.querySelector('a[href^="/item/"]')).length;
              return { cards: cards.length, links, nested, buttons: document.querySelectorAll('article button').length };
            }"""
        )
        # 星标不该把页面带走，而且要有 status 播报
        page.locator("article").first.locator('button[aria-label="稍后再看"], button[aria-label="移出稍后再看"]').first.click()
        page.wait_for_timeout(300)
        after_star = page.evaluate(
            """() => ({
              path: location.pathname,
              status: document.querySelectorAll('[role="status"]').length,
            })"""
        )
        report["card_semantics"] = {**sem, **after_star, "ok": sem["nested"] == 0 and sem["links"] > 0 and after_star["path"] == "/" and after_star["status"] > 0}
        # 撤销刚才那一下星标
        page.get_by_role("button", name="撤销").first.click()
        page.wait_for_timeout(200)

        # ---- 3. Agent 心跳（会真跑一次 agent，单测拆包时用 SKIP_AGENT=1 跳过） ----
        if os.environ.get("SKIP_AGENT") == "1":
            browser.close()
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return
        page.keyboard.press("/")
        page.wait_for_timeout(400)
        page.keyboard.type("今天 B 站有什么值得看的 AI 内容")
        page.keyboard.press("Enter")
        samples = []
        deadline = time.time() + 22
        while time.time() < deadline:
            txt = page.evaluate(
                """() => {
                  const node = Array.from(document.body.querySelectorAll('div')).find(
                    (d) => (d.innerText || '').indexOf('还在跑') === 0,
                  );
                  return node ? node.innerText : '';
                }"""
            )
            txt = " ".join(str(txt).split())
            samples.append({"t": round(time.time() - (deadline - 22), 1), "text": txt})
            page.wait_for_timeout(600)
        beats = [s["text"] for s in samples if s["text"]]
        distinct = []
        for b in beats:
            if b not in distinct:
                distinct.append(b)
        report["heartbeat"] = {
            "samples_with_heartbeat": len(beats),
            "distinct": distinct[:8],
            "distinct_count": len(distinct),
            "first_beat_seconds": beats[0] if beats else "",
            "ok": len(distinct) >= 4,
        }

        browser.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
