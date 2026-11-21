
"""第三轮：对话框热键、卡片嵌套交互、移动端 AI 入口、标题。"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT/".onefeed"/"tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
BASE = os.environ.get("ONEFEED_URL", "http://127.0.0.1:8799")
OUT = ROOT/".onefeed"/"review3-beh.json"; out = {}

def main():
  with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width":1440,"height":900})
    pg = ctx.new_page()
    pg.goto(BASE + "/", wait_until="load")
    pg.wait_for_selector('a[href^="/item/"]')
    pg.wait_for_timeout(700)

    # 1) 卡片里嵌了多少可交互元素（a > button 是非法嵌套）
    out["nested"] = pg.evaluate("""() => {
      const cards = [...document.querySelectorAll('a[href^="/item/"]')];
      return {cards: cards.length, withButtons: cards.filter(c => c.querySelector('button')).length,
              buttonsPerCard: cards[0] ? cards[0].querySelectorAll('button').length : 0};
    }""")

    # 2) 卡片内星标的键盘激活：Enter 会不会同时跳走
    pg.locator('a[href^="/item/"]').first.evaluate("el => el.querySelector('button[aria-label]')?.focus()")
    before = pg.evaluate("() => ({url: location.pathname, pressed: document.activeElement?.getAttribute('aria-pressed'), label: document.activeElement?.getAttribute('aria-label')})")
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(700)
    after = pg.evaluate("() => ({url: location.pathname, pressed: document.activeElement?.getAttribute('aria-pressed'), label: document.activeElement?.getAttribute('aria-label'), title: document.title})")
    out["star_enter"] = {"before": before, "after": after}

    # 3) 收藏对话框：Tab 到按钮后再按 [ / t / ?
    if pg.evaluate("() => location.pathname") != "/":
        pg.goto(BASE + "/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]')
    pg.locator('a[href^="/item/"]').first.click()
    pg.wait_for_selector("h1", timeout=15000); pg.wait_for_timeout(900)
    pg.get_by_role("button", name="收藏", exact=True).first.click()
    pg.wait_for_timeout(400)
    # Tab 三次：textarea -> 取消 -> 保存（或移出）
    for _ in range(3): pg.keyboard.press("Tab")
    focus1 = pg.evaluate("() => ({tag: document.activeElement?.tagName, name: (document.activeElement?.innerText||'').slice(0,10), w: getComputedStyle(document.documentElement).getPropertyValue('--shell-left-w').trim(), theme: document.documentElement.classList.contains('dark'), dialogs: document.querySelectorAll('[role=dialog]').length})")
    pg.keyboard.press("[")
    pg.wait_for_timeout(450)
    bracket = pg.evaluate("() => ({w: getComputedStyle(document.documentElement).getPropertyValue('--shell-left-w').trim(), theme: document.documentElement.classList.contains('dark'), dialogs: document.querySelectorAll('[role=dialog]').length})")
    pg.keyboard.press("t")
    pg.wait_for_timeout(500)
    tkey = pg.evaluate("() => ({w: getComputedStyle(document.documentElement).getPropertyValue('--shell-left-w').trim(), theme: document.documentElement.classList.contains('dark'), dialogs: document.querySelectorAll('[role=dialog]').length, title: document.title})")
    pg.keyboard.press("?")
    pg.wait_for_timeout(400)
    q = pg.evaluate("() => ({dialogs: document.querySelectorAll('[role=dialog]').length, help: [...document.querySelectorAll('[role=dialog]')].map(d => d.getAttribute('aria-label'))})")
    out["fav_dialog_after_tab"] = {"focus": focus1, "bracket": bracket, "t": tkey, "question": q}
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300); pg.keyboard.press("Escape"); pg.wait_for_timeout(300)

    # 4) 标题：设置页 / 市场页
    pg.goto(BASE + "/settings", wait_until="load"); pg.wait_for_timeout(900)
    out["title_settings"] = pg.title()
    pg.goto(BASE + "/market", wait_until="load"); pg.wait_for_timeout(900)
    out["title_market"] = pg.title()

    # 5) 移动端 AI 唤起器
    m = b.new_context(viewport={"width":390,"height":844}, is_mobile=True, has_touch=True, device_scale_factor=3,
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
    mp = m.new_page(); mp.goto(BASE + "/", wait_until="load"); mp.wait_for_selector('a[href^="/item/"]'); mp.wait_for_timeout(1500)
    out["mobile_launcher"] = mp.evaluate("""() => {
      const btn = document.querySelector('button[aria-label="打开 AI 助手"]');
      const r = btn?.getBoundingClientRect();
      const viewport = {vw: innerWidth, vh: innerHeight};
      return {found: Boolean(btn), rect: r ? {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height), bottom: Math.round(r.bottom)} : null,
        overlapsHomeArea: r ? r.bottom > innerHeight - 34 : null, viewport, metaViewport: document.querySelector('meta[name=viewport]')?.content,
        safeBottom: getComputedStyle(document.querySelector('main') || document.body).paddingBottom};
    }""")
    m.close()
    print(json.dumps(out, ensure_ascii=False, indent=1))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    b.close()
main()
