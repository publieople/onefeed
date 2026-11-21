
"""第三轮：导航泄漏 / 移动端 / 键盘与对话框作用域。"""
from __future__ import annotations
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
BASE2 = os.environ.get("ONEFEED_URL2", "http://127.0.0.1:8801")
OUT = ROOT / ".onefeed" / "review3-ux.json"
out = {}

def heap(page):
    return page.evaluate("() => performance.memory ? Math.round(performance.memory.usedJSHeapSize/1048576*10)/10 : null")

def main():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)

        # ---------- A. 导航往返：堆 / 节点 / 监听器 ----------
        ctx = b.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        cdp = ctx.new_cdp_session(page)
        page.goto(BASE + "/", wait_until="load")
        page.wait_for_selector('a[href^="/item/"]')
        page.wait_for_timeout(800)
        cdp.send("HeapProfiler.enable")
        cdp.send("HeapProfiler.collectGarbage")
        rounds = [{"cards": page.evaluate("() => document.querySelectorAll('a[href^=\"/item/\"]').length"),
                   "nodes": page.evaluate("() => document.getElementsByTagName('*').length"), "heap": heap(page)}]
        for i in range(8):
            page.locator('a[href^="/item/"]').first.click()
            page.wait_for_selector("h1", timeout=15000)
            page.wait_for_timeout(500)
            page.go_back()
            page.wait_for_selector('a[href^="/item/"]', timeout=15000)
            page.wait_for_timeout(500)
            if i in (2, 4, 7):
                rounds.append({"cards": page.evaluate("() => document.querySelectorAll('a[href^=\"/item/\"]').length"),
                               "nodes": page.evaluate("() => document.getElementsByTagName('*').length"), "heap": heap(page)})
        cdp.send("HeapProfiler.collectGarbage")
        page.wait_for_timeout(300)
        rounds.append({"cards": page.evaluate("() => document.querySelectorAll('a[href^=\"/item/\"]').length"),
                       "nodes": page.evaluate("() => document.getElementsByTagName('*').length"), "heap": heap(page), "gc": True})
        obj = cdp.send("Runtime.evaluate", {"expression": "window"})["result"]["objectId"]
        win_l = cdp.send("DOMDebugger.getEventListeners", {"objectId": obj})["listeners"]
        obj2 = cdp.send("Runtime.evaluate", {"expression": "document"})["result"]["objectId"]
        doc_l = cdp.send("DOMDebugger.getEventListeners", {"objectId": obj2})["listeners"]
        out["nav_rounds"] = rounds
        out["listeners"] = {
            "window": len(win_l), "document": len(doc_l),
            "win_types": sorted({l["type"] for l in win_l}), "doc_types": sorted({l["type"] for l in doc_l}),
        }

        # ---------- B. 键盘：焦点环 + toast 语义 ----------
        page.keyboard.press("Tab")
        page.wait_for_timeout(100)
        seq = page.evaluate("""() => {
          const a = document.activeElement; const s = getComputedStyle(a);
          return {tag: a.tagName, text: (a.innerText||a.getAttribute('aria-label')||'').slice(0,30),
            outline: s.outlineStyle + ' ' + s.outlineWidth + ' ' + s.outlineColor,
            boxShadow: s.boxShadow === 'none' ? 'none' : 'yes', rect: a.getBoundingClientRect().width + 'x' + a.getBoundingClientRect().height};
        }""")
        out["first_tab"] = seq
        page.evaluate("""() => window.dispatchEvent(new CustomEvent('onefeed:toast', {detail: {text: '测试提示'}}))""")
        page.wait_for_timeout(250)
        out["toast"] = page.evaluate("""() => {
          const t = [...document.querySelectorAll('div')].find(n => n.textContent === '测试提示' && n.className.includes('fixed bottom-24'));
          if (!t) return null;
          return {role: t.getAttribute('role'), live: t.getAttribute('aria-live'), tag: t.tagName};
        }""")
        page.wait_for_timeout(2600)

        # ---------- C. 收藏对话框是否漏热键 ----------
        page.locator('a[href^="/item/"]').first.click()
        page.wait_for_selector("h1", timeout=15000)
        page.wait_for_timeout(800)
        page.get_by_role("button", name="收藏", exact=True).first.click()
        page.wait_for_timeout(400)
        before = page.evaluate("() => ({w: getComputedStyle(document.documentElement).getPropertyValue('--shell-left-w').trim(), theme: document.documentElement.classList.contains('dark'), dialogs: document.querySelectorAll('[role=dialog]').length})")
        page.keyboard.press("[")
        page.wait_for_timeout(500)
        after_bracket = page.evaluate("() => ({w: getComputedStyle(document.documentElement).getPropertyValue('--shell-left-w').trim(), theme: document.documentElement.classList.contains('dark'), dialogs: document.querySelectorAll('[role=dialog]').length})")
        page.keyboard.press("t")
        page.wait_for_timeout(400)
        after_t = page.evaluate("() => ({w: getComputedStyle(document.documentElement).getPropertyValue('--shell-left-w').trim(), theme: document.documentElement.classList.contains('dark'), dialogs: document.querySelectorAll('[role=dialog]').length})")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        out["fav_dialog_hotkeys"] = {"before": before, "after_bracket": after_bracket, "after_t": after_t}

        # ---------- D. 移动端 390 ----------
        m = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                          device_scale_factor=3, user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
        mp = m.new_page()
        mp.goto(BASE + "/", wait_until="load")
        mp.wait_for_selector('a[href^="/item/"]')
        mp.wait_for_timeout(1000)
        out["mobile_feed"] = mp.evaluate("""() => {
          const vw = innerWidth, vh = innerHeight;
          const small = [];
          for (const el of document.querySelectorAll('button, a, input, textarea')) {
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0 && (r.width < 44 || r.height < 44) && getComputedStyle(el).visibility !== 'hidden') {
              small.push({tag: el.tagName, name: (el.getAttribute('aria-label')||el.innerText||el.title||'').trim().slice(0,18), w: Math.round(r.width), h: Math.round(r.height)});
            }
          }
          const composer = document.querySelector('[data-agent-surface]');
          return {vw, vh, scrollW: document.documentElement.scrollWidth, overflowX: document.documentElement.scrollWidth > vw,
            cards: document.querySelectorAll('a[href^="/item/"]').length, smallCount: small.length, small: small.slice(0, 14),
            composer: composer ? composer.getBoundingClientRect().toJSON() : null,
            safeBottom: getComputedStyle(document.documentElement).getPropertyValue('env(safe-area-inset-bottom)').trim(),
            topbarH: document.querySelector('header')?.getBoundingClientRect().height ?? null};
        }""")
        # 点一张卡进详情，检查横向溢出与底部按钮是否被遮
        mp.locator('a[href^="/item/"]').first.click()
        mp.wait_for_selector("h1", timeout=15000)
        mp.wait_for_timeout(1200)
        out["mobile_item"] = mp.evaluate("""() => {
          const vw = innerWidth;
          const wide = [...document.querySelectorAll('main *')].filter(el => el.getBoundingClientRect().right > vw + 1).slice(0, 6).map(el => el.tagName + '.' + String(el.className).slice(0, 40));
          const btn = [...document.querySelectorAll('button')].find(b => (b.innerText||'').includes('收藏'));
          const r = btn?.getBoundingClientRect();
          return {vw, scrollW: document.documentElement.scrollWidth, overflowX: document.documentElement.scrollWidth > vw,
            wide, favBtn: r ? {top: Math.round(r.top), bottom: Math.round(r.bottom), h: Math.round(r.height)} : null,
            vh: innerHeight, launcher: document.querySelector('[data-agent-surface]') ? 'sheet' : null};
        }""")
        m.close()

        # ---------- E. 平板 820：两栏 100vh ----------
        t = b.new_context(viewport={"width": 820, "height": 1180}, has_touch=True)
        tp = t.new_page()
        tp.goto(BASE + "/", wait_until="load")
        tp.wait_for_timeout(800)
        out["tablet"] = tp.evaluate("""() => {
          const els = [...document.querySelectorAll('[class*="100vh"]')].map(el => ({cls: String(el.className).slice(0, 60), h: Math.round(el.getBoundingClientRect().height)}));
          return {vh: innerHeight, els: els.slice(0, 5), scrollW: document.documentElement.scrollWidth, vw: innerWidth};
        }""")
        t.close()

        print(json.dumps(out, ensure_ascii=False, indent=1))
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        b.close()

main()
