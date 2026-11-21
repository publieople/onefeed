
import os, sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT/".onefeed"/"tmp"; TMP.mkdir(parents=True, exist_ok=True)
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(TMP)
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8799"
out = {}
with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width":1440,"height":900})
    pg = ctx.new_page()
    # 先切暗色再重载
    pg.goto(BASE + "/", wait_until="load")
    pg.evaluate("() => localStorage.setItem('onefeed.theme','dark')")
    pg.reload(wait_until="load"); pg.wait_for_selector('a[href^="/item/"]'); pg.wait_for_timeout(600)
    out["dark_bg"] = pg.evaluate("() => getComputedStyle(document.body).backgroundColor")
    # 焦点环：Tab 到第一批可聚焦元素
    seq = []
    for i in range(5):
        pg.keyboard.press("Tab"); pg.wait_for_timeout(120)
        seq.append(pg.evaluate("""() => {
          const a = document.activeElement, s = getComputedStyle(a), r = a.getBoundingClientRect();
          return {tag: a.tagName, name: (a.getAttribute('aria-label')||a.innerText||'').trim().slice(0,20),
            outline: s.outlineStyle+' '+s.outlineWidth+' '+s.outlineColor, shadow: s.boxShadow==='none'?'none':'yes',
            bg: s.backgroundColor, w: Math.round(r.width), h: Math.round(r.height)};
        }"""))
    out["dark_tab"] = seq
    # 新标签页里从零开始 Tab：跳过链接是否显形
    pg2 = ctx.new_page()
    pg2.goto(BASE + "/", wait_until="load"); pg2.wait_for_selector('a[href^="/item/"]'); pg2.wait_for_timeout(400)
    pg2.keyboard.press("Tab"); pg2.wait_for_timeout(200)
    out["skip_link"] = pg2.evaluate("""() => {
      const a = document.activeElement, r = a.getBoundingClientRect();
      return {text: a.innerText, w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.x), y: Math.round(r.y), cls: String(a.className).slice(0,80)};
    }""")
    # 设置页保存条与提示条位置
    pg2.goto(BASE + "/settings", wait_until="load"); pg2.wait_for_timeout(1200)
    out["settings_notes"] = pg2.evaluate("""() => {
      const nodes = [...document.querySelectorAll('div')].filter(n => /fixed bottom-6/.test(String(n.className)));
      return nodes.map(n => ({cls: String(n.className).slice(0,90), z: getComputedStyle(n).zIndex, y: Math.round(n.getBoundingClientRect().y), text: n.innerText.slice(0,20)}));
    }""")
    # 数字输入校验
    out["number_input"] = pg2.evaluate("""() => {
      const inputs = [...document.querySelectorAll('input[type=number]')];
      return inputs.map(i => ({v: i.value, min: i.min, max: i.max, step: i.step, w: Math.round(i.getBoundingClientRect().width)}));
    }""")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    b.close()
