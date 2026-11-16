
"""Embed matrix probe: can these pages be iframed, and does login state follow?"""
import json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".onefeed"
TMP = STATE / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(TMP)

import urllib.request, urllib.error
from playwright.sync_api import sync_playwright

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

_OPENER = urllib.request.build_opener(_NoRedirect)

def fetch_headers(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        resp = _OPENER.open(req, timeout=20)
        return resp.status, resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.headers

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")

URLS = {
    "xhs": "https://www.xiaohongshu.com/explore/6aeac597000000000e0340ac?xsec_token=ABvnRvD6UTv9uAI53rO38JreTlBG5X4Bu08atTCszOdCI%3D&xsec_source=pc_feed",
    "douyin": "https://www.douyin.com/video/7677413413173169449",
    "iesdouyin": "https://www.iesdouyin.com/share/video/7677413413173169449/",
    "m_douyin": "https://m.douyin.com/share/video/7677413413173169449",
    "zhihu": "https://www.zhihu.com/question/2104528020287354223",
    "bili": "https://www.bilibili.com/video/BV1CCJ963ECG",
    "bili_player": "https://player.bilibili.com/player.html?bvid=BV1CCJ963ECG&autoplay=0",
}

print("== response headers ==")
for name, url in URLS.items():
    try:
        code, hdrs = fetch_headers(url)
        xfo = hdrs.get("x-frame-options")
        csp = hdrs.get("content-security-policy")
        loc = hdrs.get("location")
        print(f"  {name:12s} {code} XFO={xfo!r} CSP={(csp[:200] if csp else None)!r} loc={loc}")
    except Exception as e:
        print(f"  {name:12s} ERR {type(e).__name__}: {e}")

cookie_file = STATE / "cookies" / "xiaohongshu.json"
data = json.loads(cookie_file.read_text("utf-8"))["cookies"]
cookies = []
for c in data:
    item = {"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c.get("path", "/"),
            "secure": bool(c.get("secure")), "httpOnly": bool(c.get("httpOnly"))}
    ss = c.get("sameSite")
    if ss in ("Lax", "Strict", "None"):
        item["sameSite"] = ss
    try:
        exp = c.get("expires")
        if exp:
            item["expires"] = float(exp)
    except Exception:
        pass
    cookies.append(item)
print(f"\nloaded {len(cookies)} cookies, sameSite values: {sorted({c.get('sameSite') for c in cookies})}")

out = {}
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True,
                                args=["--disable-blink-features=AutomationControlled"])
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}, locale="zh-CN")
    ctx.add_cookies(cookies)

    def watch(page, tag):
        log = []
        page.on("console", lambda m: log.append(f"{m.type}:{m.text[:200]}") if m.type in ("error", "warning") else None)
        return log

    # A. top-level xhs with cookies
    page = ctx.new_page()
    seen = []
    def on_req(req):
        if "xiaohongshu.com" in req.url and req.resource_type == "document":
            seen.append(("doc", req.url[:90], bool(req.headers.get("cookie")), req.headers.get("cookie", "")[:60]))
    page.on("request", on_req)
    logA = watch(page, "A")
    page.goto(URLS["xhs"], wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    txt = page.inner_text("body")[:400].replace("\n", " | ")
    out["A_top_xhs"] = {"url": page.url[:100], "text": txt, "console": logA[:6], "doc_requests": seen[:3]}
    page.screenshot(path=str(STATE / ".." / "design" / "embed-xhs-top.png"))

    # B. xhs inside a third-party iframe on our host origin
    page2 = ctx.new_page()
    seen2 = []
    def on_req2(req):
        if "xiaohongshu.com" in req.url:
            seen2.append((req.resource_type, req.url.split("?")[0][:90], bool(req.headers.get("cookie"))))
    page2.on("request", on_req2)
    logB = watch(page2, "B")
    page2.goto("http://127.0.0.1:8791/", wait_until="domcontentloaded", timeout=30000)
    page2.evaluate("""(u) => {
        const f = document.createElement('iframe');
        f.id = 'probe';
        f.src = u;
        f.style = 'position:fixed;left:0;top:0;width:640px;height:800px;z-index:99999;background:#fff';
        document.body.appendChild(f);
    }""", URLS["xhs"])
    page2.wait_for_timeout(12000)
    fr = [f for f in page2.frames if "xiaohongshu.com" in (f.url or "")]
    body = ""
    if fr:
        try:
            body = fr[0].inner_text("body")[:400].replace("\n", " | ")
        except Exception as e:
            body = f"READERR {type(e).__name__}"
    out["B_iframe_xhs"] = {"frames": [f.url[:100] for f in fr], "text": body,
                           "console": logB[:8], "xhs_requests": seen2[:6]}
    page2.screenshot(path=str(STATE / ".." / "design" / "embed-xhs-iframe.png"))

    # C. zhihu iframe
    page3 = ctx.new_page()
    logC = watch(page3, "C")
    page3.goto("http://127.0.0.1:8791/", wait_until="domcontentloaded", timeout=30000)
    page3.evaluate("""(u) => {
        const f = document.createElement('iframe');
        f.id='probe'; f.src=u;
        f.style='position:fixed;left:0;top:0;width:900px;height:800px;z-index:99999;background:#fff';
        document.body.appendChild(f);
    }""", URLS["zhihu"])
    page3.wait_for_timeout(10000)
    fz = [f for f in page3.frames if "zhihu.com" in (f.url or "")]
    zbody = ""
    if fz:
        try: zbody = fz[0].inner_text("body")[:300].replace("\n", " | ")
        except Exception as e: zbody = f"READERR {type(e).__name__}"
    out["C_iframe_zhihu"] = {"frames": [f.url[:100] for f in fz], "text": zbody, "console": logC[:8]}
    page3.screenshot(path=str(STATE / ".." / "design" / "embed-zhihu-iframe.png"))

    # D. douyin iframe
    page4 = ctx.new_page()
    logD = watch(page4, "D")
    page4.goto("http://127.0.0.1:8791/", wait_until="domcontentloaded", timeout=30000)
    page4.evaluate("""(u) => {
        const f=document.createElement('iframe'); f.id='probe'; f.src=u;
        f.style='position:fixed;left:0;top:0;width:640px;height:800px;z-index:99999;background:#fff';
        document.body.appendChild(f);
    }""", URLS["douyin"])
    page4.wait_for_timeout(9000)
    out["D_iframe_douyin"] = {"frames": [f.url[:100] for f in page4.frames if "douyin" in (f.url or "")], "console": logD[:8]}
    page4.screenshot(path=str(STATE / ".." / "design" / "embed-douyin-iframe.png"))

    browser.close()

print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
