
import os, sys, json, time
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
TMP = ROOT/".onefeed"/"tmp"
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_context(viewport={"width":1440,"height":900}).new_page()
    pg.goto("http://127.0.0.1:8799/", wait_until="load")
    pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(1500)
    print("focus0:", pg.evaluate("() => document.activeElement && document.activeElement.tagName"))
    pg.keyboard.press("/")
    for ms in (150, 300, 600, 900, 1500):
        pg.wait_for_timeout(ms if ms==150 else 150)
        st = pg.evaluate("""() => {
          const s = document.querySelector('[data-agent-surface]');
          const all = [...document.querySelectorAll('input,textarea')].map(e => ({tag:e.tagName, type:e.type||'', ph:(e.placeholder||'').slice(0,20)}));
          return {surface: s && s.getAttribute('data-agent-surface'), surfHTML: s ? s.outerHTML.slice(0,160) : null,
                  inputs: all, act: document.activeElement && document.activeElement.tagName, url: location.pathname};
        }""")
        print(ms, json.dumps(st, ensure_ascii=False)[:420])
    # 灯箱 API 核对
    api = pg.evaluate("""async () => { const r = await fetch('/api/item/' + encodeURIComponent('xiaohongshu:note:6aefeb59000000001802c758')); const j = await r.json(); const it = j.item || j;
      return {imgs: (it.images||[]).length, kind: it.kind}; }""")
    print("8799 item images:", api)
    b.close()
