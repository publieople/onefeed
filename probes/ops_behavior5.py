
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
    ctx=b.new_context(viewport={"width":1440,"height":900}, permissions=["clipboard-read","clipboard-write"])
    pg=ctx.new_page()
    pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(1500)

    # 1. j/k 键盘导航
    try:
        pg.keyboard.press("j"); pg.wait_for_timeout(300)
        f1 = pg.evaluate("""() => { const a=document.activeElement; return {tag:a.tagName, href:a.getAttribute&&a.getAttribute('href'), vis:(()=>{const r=a.getBoundingClientRect(); return r.top>=0 && r.bottom<=innerHeight;})()}; }""")
        pg.keyboard.press("j"); pg.keyboard.press("j"); pg.wait_for_timeout(300)
        f2 = pg.evaluate("""() => { const a=document.activeElement; return {href:a.getAttribute&&a.getAttribute('href'), vis:(()=>{const r=a.getBoundingClientRect(); return r.top>=0 && r.bottom<=innerHeight;})()}; }""")
        pg.keyboard.press("k"); pg.wait_for_timeout(250)
        f3 = pg.evaluate("""() => document.activeElement.getAttribute && document.activeElement.getAttribute('href')""")
        check("j 键聚焦首卡", bool(f1["href"] and f1["href"].startswith("/item/")), f1)
        check("j 连续下移且保持可见", f2["href"] != f1["href"] and f2["vis"], {"f1":f1["href"][:24],"f2":f2["href"][:24]})
        check("k 键上移", f3 != f2["href"], {"f2":f2["href"][:24],"f3":(f3 or "")[:24]})
        # l/h 横向
        pg.keyboard.press("l"); pg.wait_for_timeout(250)
        f4 = pg.evaluate("() => document.activeElement.getAttribute && document.activeElement.getAttribute('href')")
        check("l 键跨列移动", f4 not in (f3,), {"from":(f3 or "")[:24],"to":(f4 or "")[:24]})
    except Exception as e:
        check("列表键盘导航", False, str(e).split("\n")[0][:130])

    # 2. 卡片菜单三项
    try:
        card = pg.locator('a[href^="/item/"]').first
        card.hover(); pg.wait_for_timeout(300)
        pg.locator('button[aria-label="更多操作"]').first.click(); pg.wait_for_timeout(400)
        items = pg.evaluate("""() => [...document.querySelectorAll('[role=menu] [role=menuitem], [role=menu] button')].map(e=>e.innerText.trim())""")
        check("卡片菜单打开且有三项", len(items)>=3, items)
        # 复制链接
        pg.evaluate("""() => { const b=[...document.querySelectorAll('[role=menu] button, [role=menu] [role=menuitem]')].find(x=>x.innerText.includes('复制')); if(b) b.click(); }""")
        pg.wait_for_timeout(600)
        toast = pg.evaluate("""() => [...document.querySelectorAll('div')].filter(e=>String(e.className).includes('bottom-24')).map(e=>(e.innerText||'').trim())[0] || null""")
        clip = pg.evaluate("""async () => { try { return await navigator.clipboard.readText(); } catch(e) { return 'ERR:'+e.message; } }""")
        check("复制链接给出 toast", bool(toast), toast)
        check("剪贴板拿到链接", isinstance(clip,str) and clip.startswith("http"), (clip or "")[:50])
    except Exception as e:
        check("卡片菜单流程", False, str(e).split("\n")[0][:130])

    # 3. 稍后再看 星标 + toast
    try:
        pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(1200)
        star = pg.locator('button[aria-label="稍后再看"]').first
        star.hover(); pg.wait_for_timeout(250)
        star.click(); pg.wait_for_timeout(700)
        after = pg.evaluate("""() => ({pressed: document.querySelectorAll('button[aria-label="移出稍后再看"]').length,
            toast: [...document.querySelectorAll('div')].filter(e=>String(e.className).includes('bottom-24')).map(e=>(e.innerText||'').trim())[0]||null})""")
        check("星标后 aria-label 切换", after["pressed"]>=1, after)
        check("收藏有 toast 反馈", bool(after["toast"]), after["toast"])
        # 撤销
        pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>x.innerText.trim()==='撤销'); if(b) b.click(); }""")
        pg.wait_for_timeout(800)
        back = pg.locator('button[aria-label="移出稍后再看"]').count()
        check("收藏条撤销生效", back==0 or back< after["pressed"], {"before":after["pressed"],"after":back})
    except Exception as e:
        check("稍后再看星标流程", False, str(e).split("\n")[0][:130])

    # 4. 右栏页签
    try:
        pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(1200)
        pg.locator('button[title*="右侧栏"]').first.click(); pg.wait_for_timeout(700)
        tabs = pg.evaluate("""() => [...document.querySelectorAll('[data-shell-drawer] button, aside button')].map(b=>(b.innerText||b.title||'').trim()).filter(Boolean).slice(0,12)""")
        click = pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>(x.innerText||'').trim().startsWith('收藏夹')); if(b){b.click(); return b.innerText.trim();} return null; }""")
        pg.wait_for_timeout(600)
        panel = pg.evaluate("""() => { const d=document.querySelector('[data-shell-drawer]'); return d ? d.innerText.replace(/\s+/g,' ').slice(0,120) : null; }""")
        check("右栏打开并切到收藏夹", bool(click and panel and ("收藏" in panel)), {"tab":click, "panel":panel})
    except Exception as e:
        check("右栏页签流程", False, str(e).split("\n")[0][:130])

    # 5. Ctrl+K 搜内容
    try:
        pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(1200)
        pg.keyboard.press("Control+k"); pg.wait_for_timeout(500)
        st = pg.evaluate("""() => { const f=document.querySelector('form input[type=text], form input'); return f ? {ph:f.placeholder, focus:document.activeElement===f} : null; }""")
        check("Ctrl+K 聚焦筛选框", bool(st and st["focus"]), st)
        if st:
            pg.keyboard.type("AI"); pg.wait_for_timeout(300)
            t0=time.perf_counter(); pg.keyboard.press("Enter"); pg.wait_for_timeout(1500)
            url = pg.url; cards = pg.locator('a[href^="/item/"]').count()
            check("提交后 URL 带 q", "q=AI" in url, url[-60:])
            check("结果有卡片", cards>0, cards)
    except Exception as e:
        check("Ctrl+K 流程", False, str(e).split("\n")[0][:130])

    # 6. Agent 历史面板
    try:
        pg.goto(BASE+"/", wait_until="load"); pg.wait_for_selector('a[href^="/item/"]', timeout=25000); pg.wait_for_timeout(1200)
        pg.locator('button[title*="右侧栏"]').first.click(); pg.wait_for_timeout(600)
        pg.evaluate("""() => { const b=[...document.querySelectorAll('button')].find(x=>(x.innerText||'').trim().startsWith('AI 助手') || (x.title||'').includes('AI')); if(b) b.click(); }""")
        pg.wait_for_timeout(700)
        opened = pg.evaluate("""() => document.querySelector('[data-shell-drawer]')?.innerText.replace(/\s+/g,' ').slice(0,140) || null""")
        check("右栏 AI 助手页签有内容", bool(opened and ("问" in opened or "聊" in opened or "Agent" in opened)), opened)
    except Exception as e:
        check("Agent 历史流程", False, str(e).split("\n")[0][:130])
    b.close()
ok=sum(1 for r in out if r["ok"]); print(f"\n=== {ok}/{len(out)} ===")
(ROOT/".onefeed"/"ops-behavior5.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
