import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from urllib.parse import urlsplit

from loguru import logger
from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from constants import HEADLESS
from max_client import MaxClient


@dataclass
class _ChatPage:
    page: Page
    crashed: bool = False

    def mark_crashed(self, _page: Page) -> None:
        self.crashed = True


class BrowserManager:
    """
    Управляет одним браузером Chromium с отдельной страницей для каждой пары чатов.
    Каждая пара имеет свой asyncio.Lock, чтобы bridge и webhook не обращались
    к странице одновременно.
    """
    _pw: Playwright | None = None
    _browser: Browser | None = None
    _context: BrowserContext | None = None
    _lifecycle_lock = asyncio.Lock()
    _pair_locks: dict[str, asyncio.Lock] = {}
    _pages: dict[str, _ChatPage] = {}
    _navigation_attempts = 3
    _auth_path = "/data/auth.json"

    @classmethod
    async def _goto(cls, page: Page, pair_name: str, url: str) -> None:
        """Открывает страницу MAX с повторами при временном сетевом таймауте."""
        chat_id = urlsplit(url).path.strip("/")
        for attempt in range(1, cls._navigation_attempts + 1):
            try:
                await MaxClient(page).open_chat(chat_id)
                return
            except PlaywrightTimeoutError:
                if attempt == cls._navigation_attempts:
                    logger.error(
                        f"[{pair_name}] Чат MAX не загрузился после "
                        f"{cls._navigation_attempts} попыток: {url}"
                    )
                    raise
                logger.warning(
                    f"[{pair_name}] Таймаут загрузки MAX, повторная попытка "
                    f"{attempt + 1}/{cls._navigation_attempts}"
                )
                await asyncio.sleep(5)

    @classmethod
    def _context_closed(cls, context: BrowserContext) -> None:
        if cls._context is context:
            cls._context = None

    @classmethod
    async def _get_context(cls) -> BrowserContext:
        async with cls._lifecycle_lock:
            if cls._context is not None and cls._browser and cls._browser.is_connected():
                return cls._context

            if cls._pw is not None:
                logger.warning("Chromium или его контекст закрыт. Запускаем браузер заново")
                previous = cls._pw
                cls._pw = cls._browser = cls._context = None
                cls._pages.clear()
                with suppress(PlaywrightError):
                    await previous.stop()

            pw = await async_playwright().start()
            try:
                browser = await pw.chromium.launch(
                    headless=HEADLESS,
                    args=[
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-gpu",
                        "--disable-extensions",
                        "--single-process",
                        "--js-flags=--max-old-space-size=256",
                    ],
                )
                context = await browser.new_context(storage_state=cls._auth_path)
            except BaseException:
                with suppress(PlaywrightError):
                    await pw.stop()
                raise

            context.on("close", cls._context_closed)
            cls._pw, cls._browser, cls._context = pw, browser, context
            return context

    @classmethod
    @asynccontextmanager
    async def page(cls, pair_name: str, initial_url: str) -> AsyncIterator[Page]:
        """Предоставляет рабочую вкладку под блокировкой пары чатов."""
        if pair_name not in cls._pair_locks:
            cls._pair_locks[pair_name] = asyncio.Lock()
        async with cls._pair_locks[pair_name]:
            context = await cls._get_context()
            entry = cls._pages.get(pair_name)
            if entry and entry.page.context is context and not entry.page.is_closed():
                if not entry.crashed:
                    yield entry.page
                    return
                with suppress(PlaywrightError):
                    await entry.page.close()

            page = await context.new_page()
            entry = _ChatPage(page)
            page.on("crash", entry.mark_crashed)
            try:
                await cls._goto(page, pair_name, initial_url)
                if not cls.is_session_valid(page):
                    raise RuntimeError(
                        "Сессия Max истекла. Обновите auth.json: "
                        "запустите local-auth/get_auth.py"
                    )
            except BaseException:
                with suppress(PlaywrightError):
                    await page.close()
                raise

            cls._pages[pair_name] = entry
            yield page

    @classmethod
    async def save_auth_state(cls, path: str = _auth_path) -> None:
        """Сохраняет актуальное состояние сессии (куки, localStorage) в auth.json."""
        async with cls._lifecycle_lock:
            if cls._context is not None and cls._browser and cls._browser.is_connected():
                await cls._context.storage_state(path=path)

    @classmethod
    def is_session_valid(cls, page: Page) -> bool:
        """Возвращает False если страница оказалась на экране входа/авторизации."""
        url = page.url
        return "web.max.ru" in url and "/login" not in url and "/auth" not in url
