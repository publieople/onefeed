
import os, sys, json, time
from pathlib import Path
ROOT = Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
for k in ("TMP","TEMP","TMPDIR"): os.environ[k]=str(ROOT/".onefeed"/"tmp")
sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright
BASE="http://127.0.0.1:8799"
out=[]
def check(n,c,d=""):
    out.append({"name":n,"ok":bool(c),"detail":str(d)[:300]}); print(("PASS " if c else "FAIL ")+n+("  :: "+str(d)[:240] if d else ""), flush=True)
with sync_playwright() as p:
    b=p.chromium.launch(channel="chrome", headless=True)
    pg=b.new_context(viewport={"width":1440,"height":900}).new_page()

    # A. 右栏 pinned 页签
    try:
        pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(1500)
        pg.locator('button[title*="右侧栏"]').first.click(); pg.wait_for_timeout(800)
        st=[]
        for name in ("收藏夹","AI 总结","稍后再看"):
            clicked = pg.evaluate("""(nm) => { const b=[...document.querySelectorAll('button')].find(x=>(x.innerText||'').trim().startsWith(nm)); if(b){b.click(); return true;} return false; }""", name)
            pg.wait_for_timeout(600)
            txt = pg.evaluate("""() => { const a=document.querySelector('aside'); return a ? a.innerText.replace(/\s+/g,' ').slice(0,110) : null; }""")
            st.append({"tab":name,"clicked":clicked,"panel":txt})
        check("右栏页签可切换且有内容", all(x["clicked"] and x["panel"] for x in st), st)
    except Exception as e:
        check("右栏页签", False, str(e).split("\n")[0][:130])

    # B. 稍后再看列表移除 + 撤销
    try:
        pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(1200)
        pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='稍后再看'||/稍后再看/.test(x.innerText||'')); if(b) b.click(); }""")
        pg.wait_for_timeout(400)
        # 先加两条
        for i in range(2):
            pg.locator('button[aria-label="稍后再看"]').first.click(); pg.wait_for_timeout(500)
        pg.locator('button[title*="右侧栏"]').first.click(); pg.wait_for_timeout(800)
        pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>(x.innerText||'').trim().startsWith('稍后再看')); if(b) b.click(); }""")
        pg.wait_for_timeout(700)
        cnt = pg.evaluate("""() => { const a=document.querySelector('aside'); return a ? a.innerText.replace(/\s+/g,' ').slice(0,140) : null; }""")
        rm = pg.evaluate("""() => { const a=document.querySelector('aside'); if(!a) return 0;
            return [...a.querySelectorAll('button')].filter(b=>/移除|叉|删除/.test((b.title||'')+(b.getAttribute('aria-label')||'')+b.innerText)).length; }""")
        check("稍后再看列表有移除控件", rm>0, {"list":cnt, "rm":rm})
    except Exception as e:
        check("稍后再看列表", False, str(e).split("\n")[0][:130])

    # C. 设置页保存
    try:
        pg.goto(BASE+"/settings", wait_until="load"); pg.wait_for_timeout(2200)
        pg.locator('button:has-text("采集与排序")').first.click(); pg.wait_for_timeout(700)
        inp = pg.locator('input[type=number]').first
        old = inp.input_value()
        inp.fill("13"); pg.wait_for_timeout(400)
        pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='保存'); if(b) b.click(); }""")
        pg.wait_for_timeout(2000)
        note = pg.evaluate("""() => { const e=[...document.querySelectorAll('div')].filter(x=>String(x.className).includes('bottom-6')&&(x.innerText||'').trim()).pop();
            return e ? {t:(e.innerText||'').replace(/\s+/g,' ').slice(0,40), z:getComputedStyle(e).zIndex, y:Math.round(e.getBoundingClientRect().y)} : null; }""")
        bar = pg.evaluate("""() => [...document.querySelectorAll('div')].some(e=>(e.innerText||'').includes('有未保存的改动'))""")
        check("保存后出现结果提示", bool(note), note)
        check("保存后保存条消失", not bar)
        api = pg.evaluate("""async () => { const r = await fetch('/api/settings'); const j = await r.json(); return (j.settings||j).collect?.per_plugin_limit ?? (j.settings||j).per_plugin_limit; }""")
        check("写入生效", str(api)=="13", api)
        # 改回去
        inp.fill(old or "12"); pg.wait_for_timeout(300)
        pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='保存'); if(b) b.click(); }""")
        pg.wait_for_timeout(1500)
    except Exception as e:
        check("设置页保存流程", False, str(e).split("\n")[0][:130])

    # D. 插件开关
    try:
        pg.goto(BASE+"/settings", wait_until="load"); pg.wait_for_timeout(2200)
        pg.locator('button:has-text("已装插件")').first.click(); pg.wait_for_timeout(900)
        before = pg.evaluate("""() => { const b=document.querySelector('button[title="点击停用"]')||document.querySelector('button[title="点击启用"]'); return b?{title:b.title, ap:b.getAttribute('aria-pressed'), role:b.getAttribute('role'), cls:b.className.slice(-40)}:null; }""")
        clicked = pg.evaluate("""() => { const b=document.querySelector('button[title="点击停用"]'); if(b){b.click(); return true;} return false; }""")
        pg.wait_for_timeout(1200)
        after = pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].filter(x=>/点击停用|点击启用/.test(x.title)); return b.map(x=>({t:x.title})); }""")
        check("插件开关可点", clicked, before)
        check("开关状态有变化", any("点击启用" in x["t"] for x in after), after[:3])
        # 还原
        pg.evaluate("""() => { const b=document.querySelector('button[title="点击启用"]'); if(b) b.click(); }""")
        pg.wait_for_timeout(900)
    except Exception as e:
        check("插件开关流程", False, str(e).split("\n")[0][:130])
    b.close()
ok=sum(1 for r in out if r["ok"]); print(f"\n=== {ok}/{len(out)} ===")
(ROOT/".onefeed"/"ops-behavior6.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
