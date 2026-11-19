import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
TMP = ROOT / ".onefeed" / "tmp"
for k in ("TMP", "TEMP", "TMPDIR"):
    os.environ[k] = str(TMP)
from playwright.sync_api import sync_playwright
BASE = "http://127.0.0.1:8799"
OUT = ROOT / "design" / "review"
sys.stdout.reconfigure(encoding="utf-8")

def rail(page):
    return page.evaluate(""" () => {
      const box = document.querySelector('[aria-label="按平台筛选"]');
      if (!box) return null;
      const inner = box.querySelector('div');
      return {
        scrollW: inner ? inner.scrollWidth : null,
        clientW: inner ? inner.clientWidth : null,
        overflow: inner ? inner.scrollWidth - inner.clientWidth : null,
        fadeEl: !!box.parentElement.querySelector('[class*=fade]'),
        chips: [...box.querySelectorAll('button')].length
      };
    } """)

def chip_colors(page):
    return page.evaluate(""" () => {
      const btns = [...document.querySelectorAll('[aria-label="按平台筛选"] button')];
      const pressed = btns.filter(b => b.getAttribute('aria-pressed') === 'true').slice(0, 2);
      const masks = [...document.querySelectorAll('[aria-label="按平台筛选"] span')].map(s => {
        const st = getComputedStyle(s);
        return { cls: s.className.slice(0, 60), bg: st.backgroundColor, op: st.opacity };
      }).slice(0, 6);
      return {
        pressed: pressed.map(b => { const s = getComputedStyle(b); return { t: b.innerText.trim().slice(0,8), color: s.color, bg: s.backgroundColor }; }),
        masks
      };
    } """)

def input_focus(page):
    return page.evaluate(""" () => {
      const inputs = [...document.querySelectorAll('input, textarea')];
      return inputs.slice(0, 6).map(el => {
        const s = getComputedStyle(el);
        return { cls: el.className.slice(0, 50), outline: s.outlineStyle + ' ' + s.outlineWidth, shadow: s.boxShadow.slice(0, 40) };
      });
    } """)

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="networkidle")
    page.wait_for_timeout(1500)
    print("RAIL 390", json.dumps(rail(page), ensure_ascii=False))
    print("CHIP light", json.dumps(chip_colors(page), ensure_ascii=False))
    print("THEME-COLOR", json.dumps(page.evaluate("() => document.querySelector('meta[name=theme-color]').content")))
    # 暗色
    page.click('button[aria-label^="切换到"]')
    page.wait_for_timeout(600)
    print("CHIP dark", json.dumps(chip_colors(page), ensure_ascii=False))
    print("THEME-COLOR dark", json.dumps(page.evaluate("() => document.querySelector('meta[name=theme-color]').content")))
    page.screenshot(path=str(OUT / "chip-dark-390.png"), clip={"x": 0, "y": 110, "width": 390, "height": 120})
    page.click('button[aria-label^="切换到"]')
    page.wait_for_timeout(400)
    # 输入框焦点：AI dock
    inp = page.locator('input').first
    inp.click()
    page.wait_for_timeout(700)
    print("AI DOCK aria", json.dumps(page.evaluate(""" () => {
      const f = document.querySelector('form');
      const panel = document.querySelector('[role=dialog]');
      return { formAria: f ? f.getAttribute('aria-expanded') : null, dialog: !!panel,
               escHint: document.body.innerHTML.includes('Esc'), inputAria: document.querySelector('input')?.getAttribute('aria-label') };
    } """)))
    page.screenshot(path=str(OUT / "aidock-open-390.png"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    print("after ESC still open?", page.evaluate("() => !!document.querySelector('input') && document.activeElement.tagName"))
    # 设置页输入框 focus
    page.goto(BASE + "/settings", wait_until="networkidle")
    page.wait_for_timeout(1200)
    print("SETTINGS inputs", json.dumps(input_focus(page), ensure_ascii=False))
    page.locator("input").nth(3).click()
    page.wait_for_timeout(200)
    print("focused input style", json.dumps(page.evaluate(""" () => {
      const el = document.activeElement; const s = getComputedStyle(el);
      return { tag: el.tagName, fv: el.matches(':focus-visible'), outline: s.outlineStyle + ' ' + s.outlineWidth, shadow: s.boxShadow.slice(0,60), border: s.borderTopColor };
    } """)))
    # nav-active
    print("NAV", json.dumps(page.evaluate(""" () => {
      const a = document.querySelector('.nav-active');
      if (!a) return null; const s = getComputedStyle(a);
      return { bg: s.backgroundColor, color: s.color, weight: s.fontWeight, before: getComputedStyle(a, '::before').content };
    } """)))
    # 页面标题字号
    page.goto(BASE + "/", wait_until="networkidle"); page.wait_for_timeout(900)
    h_feed = page.evaluate("() => getComputedStyle(document.querySelector('h1')).fontSize")
    page.goto(BASE + "/settings", wait_until="networkidle"); page.wait_for_timeout(700)
    h_set = page.evaluate("() => getComputedStyle(document.querySelector('h1')).fontSize")
    page.goto(BASE + "/market", wait_until="networkidle"); page.wait_for_timeout(700)
    h_mkt = page.evaluate("() => getComputedStyle(document.querySelector('h1')).fontSize")
    print("H1 sizes feed/settings/market", h_feed, h_set, h_mkt)
    # 重复元信息
    page.goto(BASE + "/", wait_until="networkidle"); page.wait_for_timeout(1200)
    print("META dup", json.dumps(page.evaluate(""" () => {
      const txt = [...document.querySelectorAll('span,div,p')].map(e => e.innerText || '').filter(t => t.includes('最近采集'));
      return [...new Set(txt.map(t => t.trim()))];
    } """), ensure_ascii=False))
    b.close()
