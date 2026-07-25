import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto('http://127.0.0.1:8765/')
        await page.screenshot(path='/Users/chandan/leadflow/dashboard.png', full_page=True)
        # click first stat card and screenshot again
        await page.click('.stat-card')
        await asyncio.sleep(1) # wait for modal API response
        await page.screenshot(path='/Users/chandan/leadflow/dashboard_modal.png', full_page=True)
        await browser.close()

asyncio.run(main())
