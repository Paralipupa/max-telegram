
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        print("Откройте https://web.max.ru и выполните вход по QR/паролю")
        await page.goto("https://web.max.ru")
        input("После входа нажмите Enter...")
        await context.storage_state(path="auth.json")
        print("auth.json сохранён.")
asyncio.run(main())
