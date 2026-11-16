
import sys
sys.path.insert(0, r"E:/Documents/deepseek-harness/default-workspace/onefeed")
from plugin_runtime.paths import ensure_temp_env
from plugin_runtime.capabilities import UA, _find_chrome
from playwright.sync_api import sync_playwright
ensure_temp_env()
logs = []
with sync_playwright() as pw:
    b = pw.chromium.launch(executable_path=_find_chrome(), headless=True,
                           args=["--disable-blink-features=AutomationControlled", "--autoplay-policy=no-user-gesture-required"])
    pg = b.new_page(viewport={"width":900,"height":560}, user_agent=UA, locale="zh-CN")
    pg.on("console", lambda m: logs.append(f"{m.type}: {m.text[:120]}"))
    pg.on("requestfailed", lambda r: logs.append(f"FAILED {r.url[:90]} {r.failure}"))
    pg.goto("http://127.0.0.1:8793/embed_probe2.html", wait_until="networkidle", timeout=60000)
    pg.wait_for_timeout(6000)
    fr = next((f for f in pg.frames if "aweme_id" in (f.url or "") or "7677413413173169449" in (f.url or "")), None)
    print("frame:", fr.url[:80] if fr else None)
    if fr:
        try:
            btn = fr.query_selector(".xgplayer-start, .xgplayer-play, [class*=play]")
            print("play btn:", btn is not None)
            if btn: btn.click(); print("clicked")
        except Exception as e:
            print("click err", str(e)[:80])
        pg.wait_for_timeout(8000)
        st = fr.evaluate("""() => { const v = document.querySelector('video');
            return v ? {currentTime: v.currentTime, paused: v.paused, readyState: v.readyState,
                        err: v.error && v.error.code, src: (v.currentSrc||'').slice(0,80)} : null; }""")
        print("video state:", st)
        pg.screenshot(path="design/embed-douyin-player-playing.png")
    b.close()
print("--- logs ---")
for m in logs[:20]: print(" ", m)
