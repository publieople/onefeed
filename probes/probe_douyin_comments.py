# -*- coding: utf-8 -*-
"""探针：抖音评论接口（/aweme/v1/web/comment/list/）真实响应结构。"""
import json, sys, pathlib
ROOT = pathlib.Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
sys.path.insert(0, str(ROOT))
from plugin_runtime.paths import ensure_temp_env, browser_profile
from plugin_runtime.capabilities import _find_chrome, UA

ensure_temp_env()
from playwright.sync_api import sync_playwright

VIDEO = sys.argv[1] if len(sys.argv) > 1 else "7708406168997121330"
URL = "https://www.douyin.com/video/" + VIDEO

prepared = []
cookie_file = ROOT / ".onefeed" / "cookies" / "douyin.json"
if cookie_file.exists():
    data = json.loads(cookie_file.read_text(encoding="utf-8"))
    for c in data.get("cookies") or []:
        if not c.get("name"):
            continue
        prepared.append({"name": c["name"], "value": c.get("value", ""),
                         "domain": c.get("domain") or ".douyin.com", "path": c.get("path") or "/",
                         "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure")),
                         "sameSite": c.get("sameSite") or "Lax"})
print("cookies:", len(prepared))

profile = browser_profile("douyin")
profile.mkdir(parents=True, exist_ok=True)
grabbed = []

def on_response(resp):
    if "/aweme/v1/web/comment/list/" not in resp.url:
        return
    try:
        j = resp.json()
    except Exception as exc:
        grabbed.append({"url": resp.url[:160], "err": str(exc)[:100]})
        return
    rows = j.get("comments") or []
    def slim(c):
        u = c.get("user") or {}
        return {
            "cid": c.get("cid"),
            "text_head": str(c.get("text") or "")[:100],
            "text_len": len(str(c.get("text") or "")),
            "nickname": u.get("nickname"),
            "uid": u.get("uid"),
            "sec_uid": str(u.get("sec_uid") or "")[:30],
            "avatar": str((u.get("avatar_thumb") or {}).get("url_list", [""])[0])[:60] if u.get("avatar_thumb") else None,
            "digg_count": c.get("digg_count"),
            "reply_comment_total": c.get("reply_comment_total"),
            "create_time": c.get("create_time"),
            "keys": sorted(c.keys()),
        }
    grabbed.append({
        "url": resp.url[:260],
        "cursor": j.get("cursor"),
        "has_more": j.get("has_more"),
        "total": j.get("total"),
        "n": len(rows),
        "first": slim(rows[0]) if rows else None,
    })

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(profile), executable_path=_find_chrome(), headless=True,
        locale="zh-CN", viewport={"width": 1440, "height": 900}, user_agent=UA,
        args=["--disable-blink-features=AutomationControlled", "--window-size=1440,900"],
    )
    if prepared:
        ctx.add_cookies(prepared)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    cands = page.evaluate("""() => {
      const out = [];
      document.querySelectorAll('*').forEach(el => {
        const r = el.getBoundingClientRect();
        if (el.scrollHeight > el.clientHeight + 200 && r.width > 180 && r.height > 180) {
          out.push({tag: el.tagName.toLowerCase(),
                    cls: (el.className && el.className.toString().slice(0, 90)) || el.id || '',
                    x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
                    sh: el.scrollHeight, ch: el.clientHeight});
        }
      });
      return out.slice(0, 25);
    }""")
    print("SCROLLERS:", json.dumps(cands, ensure_ascii=False)[:1200])
    page.mouse.move(1180, 620)
    for i in range(14):
        page.mouse.wheel(0, 1100)
        page.wait_for_timeout(1000)
    page.screenshot(path=str(ROOT / "probes" / "tmp_douyin_comments.png"))
    txt = page.evaluate("() => document.body.innerText")
    idx = txt.find("评论")
    print("TEXT_AROUND:", txt[max(0, idx - 100): idx + 1200])
    page.wait_for_timeout(3000)
    print("URL_NOW:", page.url[:120])
    print("TITLE:", page.title()[:80])
    print("REQUESTS:", len(grabbed))
    print("SEQ:", [(g.get("cursor"), g.get("has_more"), g.get("n")) for g in grabbed])
    uniq = {}
    for g in grabbed:
        pass
    print("FIRST:", json.dumps(grabbed[0], ensure_ascii=False)[:2500] if grabbed else None)
    ctx.close()
