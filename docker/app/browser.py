import asyncio
from playwright.async_api import async_playwright
from constants import HEADLESS


class BrowserManager:
    """
    Управляет одним браузером Chromium с отдельной страницей для каждой пары чатов.
    Каждая пара имеет свой asyncio.Lock, чтобы bridge и webhook не обращались
    к странице одновременно.
    """
    _pw = None
    _browser = None
    _context = None
    # pair_name → {"page": Page, "lock": asyncio.Lock}
    _pages: dict[str, dict] = {}

    @classmethod
    async def get(cls, pair_name: str, initial_url: str) -> dict:
        """Возвращает {page, lock} для пары. При первом вызове инициализирует браузер."""
        if pair_name in cls._pages:
            return cls._pages[pair_name]

        if cls._browser is None:
            cls._pw = await async_playwright().start()
            cls._browser = await cls._pw.chromium.launch(
                headless=HEADLESS,
                args=[
                    "--disable-dev-shm-usage",  # Не использовать /dev/shm (ограничен в Docker до 64MB)
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-extensions",
                    "--single-process",                      # Один процесс — экономия ~200MB RAM
                    "--js-flags=--max-old-space-size=256",  # Ограничить V8 heap
                ],
            )
            cls._context = await cls._browser.new_context(storage_state="/data/auth.json")

        page = await cls._context.new_page()
        await page.goto(initial_url)

        if not cls.is_session_valid(page):
            await cls._browser.close()
            cls._browser = None
            cls._context = None
            raise RuntimeError(
                "Сессия Max истекла. Обновите auth.json: запустите local-auth/get_auth.py"
            )

        cls._pages[pair_name] = {
            "page": page,
            "lock": asyncio.Lock(),
            "url": initial_url,
        }
        return cls._pages[pair_name]

    @classmethod
    async def reload_page(cls, pair_name: str) -> None:
        """Перезагружает страницу пары для освобождения памяти браузера (SPA накапливает DOM)."""
        entry = cls._pages.get(pair_name)
        if not entry:
            return
        await entry["page"].goto(entry["url"])
        await entry["page"].wait_for_selector(".bubble", timeout=15000)

    @classmethod
    async def save_auth_state(cls, path: str = "/data/auth.json") -> None:
        """Сохраняет актуальное состояние сессии (куки, localStorage) в auth.json."""
        if cls._context is None:
            return
        await cls._context.storage_state(path=path)
        logger.info(f"auth.json обновлён ({path})")

    @classmethod
    def is_session_valid(cls, page) -> bool:
        """Возвращает False если страница оказалась на экране входа/авторизации."""
        url = page.url
        return "web.max.ru" in url and "/login" not in url and "/auth" not in url
