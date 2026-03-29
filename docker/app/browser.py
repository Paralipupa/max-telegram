import asyncio
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
        browser = await pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-dev-shm-usage",  # Не использовать /dev/shm (ограничен в Docker до 64MB)
                "--no-sandbox",
                "--disable-gpu",
                "--disable-extensions",
                "--single-process",          # Один процесс вместо нескольких — экономия ~200MB RAM
                "--js-flags=--max-old-space-size=256",  # Ограничить V8 heap
            ],
        )
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

    @classmethod
    async def reload_page(cls):
        """Перезагружает страницу чата для освобождения памяти браузера (SPA накапливает DOM)."""
        if not cls._instance:
            return
        page = cls._instance["page"]
        await page.goto(PAGE_URL)
        await page.wait_for_selector(".bubble", timeout=15000)
