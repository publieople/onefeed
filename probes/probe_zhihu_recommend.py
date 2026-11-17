# -*- coding: utf-8 -*-
"""探针：注入知乎 cookie，打开首页，看页面自己发的推荐流/关注流响应。"""
import json, sys, pathlib
ROOT = pathlib.Path(r"E:\Documents\deepseek-harness\default-workspace\onefeed")
sys.path.insert(0, str(ROOT))
from plugin_runtime.paths import ensure_temp_env, browser_profile          # noqa: E402
from plugin_runtime.capabilities import _find_chrome, UA                    # noqa: E402

ensure_temp_env()
from playwright.sync_api import sync_playwright                             # noqa: E402

PATTERNS = ("/api/v3/feed/topstory/recommend", "/api/v3/moments", "/api/v3/feed/topstory")
cookie_file = ROOT / ".onefeed" / "cookies" / "zhihu.json"
data = json.loads(cookie_file.read_text(encoding="utf-8"))
prepared = []
for c in data.get("cookies") or []:
    if not c.get("name"):
        continue
    prepared.append({
        "name": c["name"], "value": c.get("value", ""),
        "domain": c.get("domain") or ".zhihu.com", "path": c.get("path") or "/",
        "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure")),
        "sameSite": c.get("sameSite") or "Lax",
    })

profile = browser_profile("zhihu")
profile.mkdir(parents=True, exist_ok=True)
bodies = []

def on_response(resp):
    if any(p in resp.url for p in PATTERNS):
        try:
            bodies.append({"url": resp.url, "json": resp.json()})
        except Exception as exc:
            bodies.append({"url": resp.url, "err": str(exc)})

with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(profile), executable_path=_find_chrome(), headless=True,
        locale="zh-CN", viewport={"width": 1440, "height": 900}, user_agent=UA,
        args=["--disable-blink-features=AutomationControlled", "--window-size=1440,900"],
    )
    ctx.add_cookies(prepared)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.on("response", on_response)
    page.goto("https://www.zhihu.com/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    print("URL:", page.url)
    print("TITLE:", page.title())
    for _ in range(4):
        page.mouse.wheel(0, 2400)
        page.wait_for_timeout(2500)
    print("N_BODIES:", len(bodies))
    for b in bodies[:5]:
        j = b.get("json")
        if not isinstance(j, dict):
            print("  ", b["url"][:120], "ERR", b.get("err"))
            continue
        keys = sorted(j.keys())[:12]
        print("  ", b["url"][:110])
        print("     keys:", keys)
        arr = j.get("data")
        if isinstance(arr, list) and arr:
            print("     n_data:", len(arr))
            first = arr[0]
            if isinstance(first, dict):
                print("     first keys:", sorted(first.keys()))
                tgt = first.get("target") if isinstance(first.get("target"), dict) else first
                print("     target keys:", sorted(tgt.keys())[:25])
                print("     type:", tgt.get("type"), "id:", tgt.get("id"))
                q = tgt.get("question") or {}
                print("     question title:", str(q.get("title") or tgt.get("title") or "")[:80])
                print("     excerpt:", str(tgt.get("excerpt") or "")[:100])
        else:
            print("     data type:", type(j.get("data")).__name__)
    out = ROOT / "probes" / "tmp_zhihu_recommend.json"
    out.write_text(json.dumps(bodies, ensure_ascii=False)[:4_000_000], encoding="utf-8")
    print("SAVED:", out)
    ctx.close()
