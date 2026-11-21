import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".onefeed" / "tmp"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:8799"

async def shot(pg, path):
    await pg.screenshot(path=str(OUT / path))

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel="chrome", headless=True,
            args=["--disable-background-timer-throttling","--disable-renderer-backgrounding"])
        pg = await b.new_page(viewport={"width":1440,"height":900}, device_scale_factor=2)
        await pg.goto(BASE + "/", wait_until="domcontentloaded")
        await pg.evaluate("localStorage.setItem('onefeed.theme','light')")
        await pg.reload(wait_until="domcontentloaded")
        await pg.wait_for_timeout(1200)
        await shot(pg, "t1-feed-light.png")

        await pg.evaluate("localStorage.setItem('onefeed.theme','dark')")
        await pg.reload(wait_until="domcontentloaded")
        await pg.wait_for_timeout(1200)
        await shot(pg, "t1-feed-dark.png")

        href = await pg.evaluate("() => document.querySelector('article a[href^=\"/item/\"]')?.getAttribute('href')")
        await pg.goto(BASE + href, wait_until="domcontentloaded")
        await pg.wait_for_timeout(2500)
        await shot(pg, "t1-item-dark.png")

        await pg.evaluate("localStorage.setItem('onefeed.theme','light')")
        await pg.reload(wait_until="domcontentloaded")
        await pg.wait_for_timeout(2500)
        await shot(pg, "t1-item-light.png")

        await pg.goto(BASE + "/settings", wait_until="domcontentloaded")
        await pg.wait_for_timeout(1000)
        await shot(pg, "t1-settings-light.png")

        await pg.goto(BASE + "/", wait_until="domcontentloaded")
        await pg.wait_for_timeout(900)
        data = await pg.evaluate("""() => {
          const card = document.querySelector('article');
          const h3 = card && card.querySelector('h3');
          const star = card && card.querySelector('button[aria-label*="稍后再看"]');
          const cs = (el) => el ? getComputedStyle(el) : null;
          const root = getComputedStyle(document.documentElement);
          return {
            cardBg: cs(card)?.backgroundColor,
            cardRadius: cs(card)?.borderRadius,
            h3Font: cs(h3)?.fontFamily,
            h3Size: cs(h3)?.fontSize,
            starColor: cs(star)?.color,
            bodyBg: getComputedStyle(document.body).backgroundColor,
            accent: root.getPropertyValue("--c-accent").trim(),
            paper: root.getPropertyValue("--c-paper").trim(),
          };
        }""")
        print(data)
        await b.close()

asyncio.run(main())

