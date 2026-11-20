
import os, sys, json
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
TMP = ROOT / ".onefeed" / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP","TEMP","TMPDIR"): os.environ[k] = str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_context(viewport={"width":1440,"height":900}).new_page()
    # 收藏对话框
    pg.goto("http://127.0.0.1:8799/?p=bilibili", wait_until="load")
    pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(900)
    pg.locator('a[href^="/item/"]').first.click(); pg.wait_for_url("**/item/**", timeout=15000); pg.wait_for_timeout(2400)
    pg.get_by_role("button", name="收藏", exact=True).first.click(); pg.wait_for_timeout(500)
    print("DIALOG:", pg.evaluate("""() => { const d = document.querySelector('[role=dialog]');
      return d ? {text: d.innerText, buttons: [...d.querySelectorAll('button')].map(b => ({t:(b.innerText||'').trim(), dis:b.disabled, title:b.title}))} : null; }"""))
    pg.keyboard.press("Escape"); pg.wait_for_timeout(300)
    # 市场
    pg.goto("http://127.0.0.1:8799/market", wait_until="load"); pg.wait_for_timeout(2200)
    print("MARKET buttons:", pg.evaluate("""() => [...document.querySelectorAll('button')].map(b => (b.innerText||'').trim()).filter(Boolean).slice(0,30)"""))
    print("MARKET cards:", pg.evaluate("""() => [...document.querySelectorAll('article,li,div')].filter(e => (e.innerText||'').includes('已装') || (e.innerText||'').includes('安装')).length"""))
    # Agent composer
    pg.goto("http://127.0.0.1:8799/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(1000)
    pg.keyboard.press("/"); pg.wait_for_timeout(700)
    print("AGENT:", pg.evaluate("""() => { const s = document.querySelector('[data-agent-surface]');
      return s ? {surface: s.getAttribute('data-agent-surface'), inputs: [...s.querySelectorAll('input,textarea')].map(e => ({tag:e.tagName, type:e.type, ph:e.placeholder, cls:(e.className||'').slice(0,60)}))} : null; }"""))
    pg.keyboard.press("Escape")
    # 8801 多图
    pg2 = b.new_context(viewport={"width":1440,"height":900}).new_page()
    r = pg2.goto("http://127.0.0.1:8801/item/xiaohongshu%3Anote%3A6aefeb59000000001802c758", wait_until="load")
    print("8801 status", r.status)
    pg2.wait_for_timeout(3000)
    print("8801 item:", pg2.evaluate("""() => ({title: (document.querySelector('h1')||{}).innerText,
      imgs: document.querySelectorAll('main img').length, lb: document.querySelectorAll('[data-lb-index]').length,
      text: (document.querySelector('main')||{}).innerText?.slice(0,160)})"""))
    b.close()
