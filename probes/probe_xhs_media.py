
import json, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
import sys
ROOT = Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed")
sys.path.insert(0, str(ROOT))
from plugin_runtime.paths import ensure_temp_env, browser_profile
from plugin_runtime.capabilities import UA, _find_chrome

NOTE = ("https://www.xiaohongshu.com/explore/6aeac597000000000e0340ac"
        "?xsec_token=ABvnRvD6UTv9uAI53rO38JreTlBG5X4Bu08atTCszOdCI%3D&xsec_source=pc_feed")
cookies = json.loads((ROOT / ".onefeed/cookies/xiaohongshu.json").read_text(encoding="utf-8"))["cookies"]
ensure_temp_env()
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(user_data_dir=str(browser_profile("xiaohongshu_probe2")),
        executable_path=_find_chrome(), headless=True, locale="zh-CN",
        viewport={"width": 1440, "height": 900}, user_agent=UA,
        args=["--disable-blink-features=AutomationControlled"])
    ctx.add_cookies([{"name": c["name"], "value": c["value"], "domain": c.get("domain") or ".xiaohongshu.com",
                      "path": c.get("path") or "/", "httpOnly": bool(c.get("httpOnly")),
                      "secure": bool(c.get("secure")), "sameSite": c.get("sameSite") or "Lax"} for c in cookies])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(NOTE, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    out = page.evaluate("""() => {
      const s = window.__INITIAL_STATE__ || {};
      const m = s.note && s.note.noteDetailMap; const res = {video: null, img: null};
      if (m) { const keys = Object.keys(m); const n = keys.length ? (m[keys[0]].note || {}) : {};
        const st = ((n.video || {}).media || {}).stream || {};
        for (const c of Object.keys(st)) { const arr = st[c] || []; if (arr.length) { res.video = {codec: c, master: arr[0].masterUrl, backups: (arr[0].backupUrls || []).length}; break; } }
        const il = n.imageList || []; if (il.length) res.img = il[0].url || il[0].urlDefault || null;
      }
      return res; }""")
    ctx.close()
print("video:", json.dumps(out.get("video"), ensure_ascii=False)[:200])
print("img:", (out.get("img") or "")[:110])

def probe(url, referer=None, ua=UA):
    h = {"User-Agent": ua, "Range": "bytes=0-2047"}
    if referer: h["Referer"] = referer
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=25) as r:
            return r.status, r.headers.get("Content-Type"), len(r.read())
    except Exception as e:
        return getattr(e, "code", 0), None, str(e)[:80]

v = (out.get("video") or {}).get("master")
if v:
    for label, ref in (("no-referer", None), ("referer=xhs", "https://www.xiaohongshu.com/")):
        print(f" video {label}:", probe(v, ref))
i = out.get("img")
if i:
    for label, ref in (("no-referer", None), ("referer=xhs", "https://www.xiaohongshu.com/")):
        print(f" image {label}:", probe(i, ref))
