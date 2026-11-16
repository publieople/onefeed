
"""Deeper embed probe: capture iframe document response headers + CSP source, test douyin alternatives."""
import json, os, re
from pathlib import Path
import urllib.request, urllib.error

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".onefeed"
TMP = STATE / "tmp"; TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = os.environ["TMPDIR"] = str(TMP)

from playwright.sync_api import sync_playwright

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36")

DOUYIN_ID = "7677413413173169449"
CANDIDATES = {
    "douyin_video": f"https://www.douyin.com/video/{DOUYIN_ID}",
    "douyin_player_vid": f"https://www.douyin.com/player/video?vid={DOUYIN_ID}",
    "iesdouyin_share": f"https://www.iesdouyin.com/share/video/{DOUYIN_ID}/",
    "zhihu_question": "https://www.zhihu.com/question/2104528020287354223",
    "zhihu_zhuanlan": "https://zhuanlan.zhihu.com/p/",
    "xhs_explore": "https://www.xiaohongshu.com/explore/6aeac597000000000e0340ac?xsec_token=ABvnRvD6UTv9uAI53rO38JreTlBG5X4Bu08atTCszOdCI%3D&xsec_source=pc_feed",
}

results = {}
with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    ctx = browser.new_context(user_agent=UA, viewport={"width": 1280, "height": 900}, locale="zh-CN")
    for name, url in CANDIDATES.items():
        if name == "zhihu_zhuanlan":
            continue
        page = ctx.new_page()
        logs, responses = [], []
        page.on("console", lambda m, L=logs: L.append(f"{m.type}:{m.text[:180]}") if m.type in ("error", "warning") else None)
        page.on("response", lambda r, R=responses, host=name.split("_")[0]: R.append(
            (r.request.resource_type, r.status, r.url.split("?")[0][:80],
             r.headers.get("x-frame-options"), (r.headers.get("content-security-policy") or "")[:260]))
            if r.request.resource_type == "document" else None)
        page.goto("http://127.0.0.1:8791/", wait_until="domcontentloaded", timeout=30000)
        page.evaluate("""(u) => {
            const f=document.createElement('iframe'); f.id='probe'; f.src=u;
            f.style='position:fixed;left:0;top:0;width:640px;height:820px;z-index:99999;background:#fff';
            document.body.appendChild(f);
        }""", url)
        page.wait_for_timeout(9000)
        frames = [(f.url or "")[:100] for f in page.frames if f != page.main_frame]
        text = ""
        if len(page.frames) > 1:
            try:
                text = page.frames[1].inner_text("body")[:260].replace("\n", " | ")
            except Exception as e:
                text = f"READERR {type(e).__name__}: {e}"
        shot = STATE.parent / "design" / f"embed2-{name}.png"
        page.screenshot(path=str(shot))
        results[name] = {"url": url, "frames": frames, "text": text,
                         "doc_responses": responses, "console": logs[:6], "shot": shot.name}
        page.close()
    browser.close()

# meta CSP in douyin html?
def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, r.read(400000).decode("utf-8", "replace")

try:
    st, html = fetch(f"https://www.douyin.com/video/{DOUYIN_ID}")
    metas = re.findall(r'<meta[^>]+http-equiv="?Content-Security-Policy"?[^>]*>', html, re.I)
    results["douyin_html_meta_csp"] = {"status": st, "len": len(html), "metas": [m[:400] for m in metas[:3]]}
except Exception as e:
    results["douyin_html_meta_csp"] = f"ERR {type(e).__name__}: {e}"

Path(ROOT / "probes" / "tmp_embed2.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")
print(json.dumps(results, ensure_ascii=False, indent=1)[:6000])
