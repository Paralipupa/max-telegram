import os
from playwright.async_api import async_playwright

MAX_CHAT_ID = os.getenv("MAX_CHAT_ID")
PAGE_URL = f"https://web.max.ru/{MAX_CHAT_ID}"
TAIL_LIMIT = int(os.getenv("TAIL_LIMIT", "30"))


class BrowserManager:
    _instance = None

    @classmethod
    async def get(cls):
        if cls._instance:
            return cls._instance

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True)
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
