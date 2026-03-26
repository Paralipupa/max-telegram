
from playwright.async_api import async_playwright

class BrowserManager:
    _instance = None

    @classmethod
    async def get(cls):
        if cls._instance:
            return cls._instance

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="/data/auth.json")
        page = await context.new_page()
        await page.goto("https://web.max.ru")

        cls._instance = {
            "pw": pw,
            "browser": browser,
            "context": context,
            "page": page,
        }
        return cls._instance
