import asyncio
import os
from playwright.async_api import async_playwright
from constants import PAGE_URL, HEADLESS


class BrowserManager:
    _instance = None
    # Лок предотвращает одновременное использование страницы bridge и webhook:
    # webhook делает page.goto() пока bridge читает DOM → таймаут wait_for_selector
    lock: asyncio.Lock = asyncio.Lock()

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
