import os
from playwright.async_api import async_playwright
from constants import PAGE_URL, HEADLESS
class BrowserManager:
    _instance = None

    @classmethod
    async def get(cls):
        if cls._instance:
            return cls._instance

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=HEADLESS)
        context = await browser.new_context(storage_state="/data/auth.json")
        page = await context.new_page()
        await page.goto(PAGE_URL)

        cls._instance = {
            "pw": pw,
            "browser": browser,
            "context": context,
            "page": page,
        }
        return cls._instance
