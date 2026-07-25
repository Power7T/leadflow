import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        # Same URL as before: TRAIN MOMENT MKE
        url = "https://leadflow-relay.chandango12.workers.dev/demo/train-moment-mke-148"
        print(f"Loading {url}")
        await page.goto(url, wait_until="networkidle", timeout=15000)
        await page.screenshot(path='/Users/chandan/leadflow/preview_gym_final.png')
        await browser.close()

asyncio.run(main())
