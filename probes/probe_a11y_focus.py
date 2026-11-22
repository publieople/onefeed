
from playwright.sync_api import sync_playwright
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BASE = "http://127.0.0.1:8799"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path=CHROME, headless=True)
    ctx = b.new_context(locale="zh-CN", viewport={"width":1440,"height":900})
    page = ctx.new_page()
    page.goto(BASE + "/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector('[data-vt-item] a[href^="/item/"]', timeout=15000)
    page.wait_for_timeout(600)

    link = page.query_selector('[data-vt-item] a[href^="/item/"]')
    card_id = link.evaluate("el => el.closest('[data-vt-item]').dataset.vtItem")
    link.focus()
    page.keyboard.press("Enter")
    page.wait_for_url("**/item/**", timeout=15000)
    page.wait_for_timeout(900)
    print("FOCUS_AFTER", page.evaluate("() => document.activeElement.tagName"))

    # 走站内「返回」按钮（它带 location.state.fromId）
    page.get_by_role("button", name="返回").first.click()
    page.wait_for_timeout(1400)
    print("FOCUS_BACK", page.evaluate("""(id) => {
      const a = document.activeElement;
      const holder = a && a.closest('[data-vt-item]');
      return {
        tag: a ? a.tagName : null,
        text: a ? (a.textContent || '').trim().slice(0, 22) : null,
        holder: holder ? holder.dataset.vtItem : null,
        same: holder ? holder.dataset.vtItem === id : false,
        path: location.pathname,
      };
    }""", card_id))

    # 再按 Enter 应该能重新进详情（证明焦点落在可操作元素上）
    page.keyboard.press("Enter")
    page.wait_for_timeout(700)
    print("REENTER", page.evaluate("() => location.pathname"))

    ctx.close(); b.close()
