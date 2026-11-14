
import os, sys, json, time
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
WS = r"E:\Documents\deepseek-harness\default-workspace"
TMP = os.path.join(WS, "onefeed", ".onefeed", "tmp"); os.makedirs(TMP, exist_ok=True)
for k in ("TMP", "TEMP", "TMPDIR"): os.environ[k] = TMP
from playwright.sync_api import sync_playwright

QR_IMG = os.path.join(WS, "onefeed", "probes", "xhs_qr_cdp.png")
COOKIE_OUT = os.path.join(WS, "onefeed", "probes", "tmp_xhs_cookies_cdp.json")
NAMES = ("a1","webId","web_session","web_session_sec","id_token","websectiga",
         "sec_poison_id","xsecappid","gid","abRequestId","webBuild","loadts")

def ckmap(ctx):
    return {c["name"]: c["value"] for c in ctx.cookies() if "xiaohongshu" in (c.get("domain") or "")}

def qr_box(page):
    return page.evaluate("""() => {
        const els = [...document.querySelectorAll('img, canvas')];
        for (const e of els) {
            const r = e.getBoundingClientRect();
            const src = e.tagName === 'IMG' ? (e.currentSrc || e.src || '') : 'canvas';
            if (r.width > 100 && r.height > 100 && (src.startsWith('data:image') || e.tagName === 'CANVAS')) {
                return {x: r.x, y: r.y, width: r.width, height: r.height};
            }
        }
        return null;
    }""")

action = sys.argv[1] if len(sys.argv) > 1 else "check"
with sync_playwright() as p:
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9333")
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    if action == "qr":
        if page.url.startswith("about:") or "xiaohongshu" not in page.url:
            page.goto("https://www.xiaohongshu.com/login", wait_until="domcontentloaded", timeout=60000)
        box = None
        for _ in range(30):
            try:
                box = qr_box(page)
            except Exception:
                box = None
            if box: break
            time.sleep(1)
        if box:
            pad = 8
            page.screenshot(path=QR_IMG, clip={"x": max(box["x"]-pad,0), "y": max(box["y"]-pad,0),
                                               "width": box["width"]+2*pad, "height": box["height"]+2*pad})
        print("URL", page.url)
        print("QR", QR_IMG if box else "none", box)
    elif action == "check":
        ck = ckmap(ctx)
        ws_ = ck.get("web_session", "")
        print("URL", page.url)
        print("WS prefix=%s len=%d guest=%s" % (ws_[:10], len(ws_), ws_.startswith("040069")))
        print("KEYS", sorted(ck.keys()))
    elif action == "save":
        ck = ckmap(ctx)
        sel = {k: v for k, v in ck.items() if k in NAMES}
        json.dump({"cookies": sel}, open(COOKIE_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("URL", page.url)
        print("SAVED", COOKIE_OUT)
        print("KEYS", sorted(sel.keys()))
        print("WS prefix", sel.get("web_session","")[:10])
