
import json, sys, urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(r"E:/Documents/deepseek-harness/default-workspace/onefeed")
sys.path.insert(0, str(ROOT))
from plugin_runtime.paths import ensure_temp_env, browser_profile
from plugin_runtime.capabilities import UA, _find_chrome

NOTE = ("https://www.xiaohongshu.com/explore/6aeac597000000000e0340ac"
        "?xsec_token=ABvnRvD6UTv9uAI53rO38JreTlBG5X4Bu08atTCszOdCI%3D&xsec_source=pc_feed")
cookies = json.loads((ROOT / ".onefeed/cookies/xiaohongshu.json").read_text(encoding="utf-8"))["cookies"]
ensure_temp_env()
hits = []
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(browser_profile("xiaohongshu_probe")),
        executable_path=_find_chrome(), headless=True, locale="zh-CN",
        viewport={"width": 1440, "height": 900}, user_agent=UA,
        args=["--disable-blink-features=AutomationControlled"])
    ctx.add_cookies([{"name": c["name"], "value": c["value"], "domain": c.get("domain") or ".xiaohongshu.com",
                      "path": c.get("path") or "/", "httpOnly": bool(c.get("httpOnly")),
                      "secure": bool(c.get("secure")), "sameSite": c.get("sameSite") or "Lax"} for c in cookies])
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    def on_resp(r):
        if "api/sns/web/v1" in r.url:
            try: hits.append({"url": r.url, "json": r.json()})
            except Exception: pass
    page.on("response", on_resp)
    page.goto(NOTE, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(6000)
    for _ in range(3):
        page.mouse.wheel(0, 1200); page.wait_for_timeout(1200)
    data = page.evaluate("""() => {
      const s = window.__INITIAL_STATE__ || {};
      const m = s.note && s.note.noteDetailMap;
      const out = {hasState: !!s.note, mapType: m ? (m.constructor && m.constructor.name) : 'none'};
      out.notes = [];
      if (m && m.forEach) m.forEach((v, k) => { out.notes.push({key: k, note: v && v.note ? v.note : null}); });
      else if (m) { for (const k of Object.keys(m)) out.notes.push({key: k, note: m[k] && m[k].note}); }
      return out;
    }""")
    print("hasState:", data["hasState"], "mapType:", data["mapType"], "notes:", len(data["notes"]))
    for entry in data["notes"][:1]:
        n = entry["note"] or {}
        print("title:", (n.get("title") or "")[:60])
        print("desc:", (n.get("desc") or "")[:200].replace("\n", " "))
        print("type:", n.get("type"))
        imgs = n.get("imageList") or []
        print("images:", len(imgs), "img0 keys sample:", list(imgs[0].keys())[:8] if imgs else None)
        vid = n.get("video") or {}
        if vid:
            st = ((vid.get("media") or {}).get("stream") or {})
            print("stream codecs:", list(st.keys()))
            for codec in ("h264", "h265", "av1", "h266"):
                arr = st.get(codec) or []
                if arr:
                    print(f" {codec}[0]:", (arr[0].get("masterUrl") or "")[:110])
                    print(f" {codec} backups:", len(arr[0].get("backupUrls") or []))
                    break
        print("user:", ((n.get("user") or {}).get("nickname")))
        print("interact:", {k: (n.get("interactInfo") or {}).get(k) for k in ("likedCount","commentCount","collectedCount","shareCount")})
        print("time:", n.get("time"), "ip:", n.get("ipLocation"))
    print("api hits:", [h["url"].split("?")[0].split("/api/")[-1] for h in hits])
    for h in hits:
        if "comment" in h["url"] and isinstance(h["json"], dict):
            cm = (h["json"].get("data") or {})
            lst = cm.get("comments") or []
            print("comment payload keys:", list(cm.keys())[:8], "comments:", len(lst))
            if lst:
                print(" first comment:", (lst[0].get("content") or "")[:60], "| like:", (lst[0].get("like_count") or ""))
            break
    if hits:
        Path("probes/tmp_xhs_api_hits.json").write_text(json.dumps(hits, ensure_ascii=False)[:2000000], encoding="utf-8")
    ctx.close()
