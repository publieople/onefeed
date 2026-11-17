# -*- coding: utf-8 -*-
"""探针：小红书评论接口（/api/sns/web/v2/comment/page）真实响应结构。"""
import json, sys, pathlib
ROOT = pathlib.Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
sys.path.insert(0, str(ROOT))
from plugin_runtime.paths import ensure_temp_env, browser_profile
from plugin_runtime.capabilities import _find_chrome, UA

ensure_temp_env()
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.xiaohongshu.com/explore/6af770220000000024030e0e"

prepared = []
cookie_file = ROOT / ".onefeed" / "cookies" / "xiaohongshu.json"
if cookie_file.exists():
    data = json.loads(cookie_file.read_text(encoding="utf-8"))
    for c in data.get("cookies") or []:
        if not c.get("name"):
            continue
        prepared.append({"name": c["name"], "value": c.get("value", ""),
                         "domain": c.get("domain") or ".xiaohongshu.com", "path": c.get("path") or "/",
                         "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure")),
                         "sameSite": c.get("sameSite") or "Lax"})
print("cookies:", len(prepared))

profile = browser_profile("xiaohongshu")
profile.mkdir(parents=True, exist_ok=True)
grabbed = []

def on_response(resp):
    if "/api/sns/web/v2/comment/" not in resp.url and "/api/sns/web/v1/comment/" not in resp.url:
        return
    try:
        j = resp.json()
    except Exception as exc:
        grabbed.append({"url": resp.url[:160], "err": str(exc)[:100]})
        return
    rows = (j.get("data") or {}).get("comments") or j.get("comments") or []
    def slim(c):
        u = c.get("user_info") or {}
        subs = c.get("sub_comments") or []
        return {
            "id": c.get("id"),
            "text_head": str(c.get("content") or "")[:100],
            "text_len": len(str(c.get("content") or "")),
            "nickname": u.get("nickname"),
            "uid": u.get("user_id"),
            "avatar": str(u.get("image") or "")[:60],
            "like_count": c.get("like_count"),
            "sub_comment_count": c.get("sub_comment_count"),
            "sub_n": len(subs),
            "create_time": c.get("create_time"),
            "keys": sorted(c.keys()),
        }
    data = j.get("data") or {}
    grabbed.append({
        "url": resp.url[:300],
        "has_more": data.get("has_more"),
        "cursor": data.get("cursor"),
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
    page.wait_for_timeout(6000)
    page.mouse.move(1180, 620)
    for i in range(14):
        page.mouse.wheel(0, 1100)
        page.wait_for_timeout(1000)
    page.wait_for_timeout(3000)
    print("URL_NOW:", page.url[:160])
    print("TITLE:", page.title()[:80])
    print("REQUESTS:", len(grabbed))
    print("SEQ:", [(g.get("cursor"), g.get("has_more"), g.get("n")) for g in grabbed])
    print("FIRST:", json.dumps(grabbed[0], ensure_ascii=False)[:2500] if grabbed else None)
    ctx.close()
