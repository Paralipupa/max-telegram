import asyncio
from constants import TELEGRAM_PREFIX
from playwright.async_api import Page
from loguru import logger
import time
from max_message_extractors import extract_emojis, merge_caption_and_emojis
from max_message_info import bubble_to_message_info


class MaxClient:
    def __init__(self, page: Page) -> None:
        self.page: Page = page

    async def _bubble_to_message_info(self, bubble):
        return await bubble_to_message_info(bubble)

    async def open_chat(self, chat_id):
        url = f"https://web.max.ru/{chat_id}"
        for attempt in range(3):
            try:
                await self.page.goto(url)
                await self.page.wait_for_selector(
                    "[contenteditable]", timeout=15000
                )
                return
            except Exception as e:
                if "ERR_ABORTED" not in str(e) or attempt == 2:
                    raise
                await asyncio.sleep(0.3 * (attempt + 1))

    async def send_text(self, text):
        editor = await self.page.wait_for_selector("[contenteditable]")
        await editor.fill(text)
        await editor.press("Enter")

    async def read_message_text(self, msg):
        # Сначала пытаемся получить текст из span.text
        text_span = await msg.query_selector('xpath=//span[contains(@class, "text")]')
        if text_span:
            text = await text_span.text_content()
            base_text = text.strip() if text else ""
        else:
            base_text = ""

        emoji_chars = await extract_emojis(msg)
        merged = merge_caption_and_emojis(base_text or None, emoji_chars)
        return merged or None

    async def read_last_message(self):
        await self.page.wait_for_selector(".bubble", timeout=10000)
        bubbles = await self.page.query_selector_all(".bubble")
        if not bubbles:
            return None
        last_bubble = bubbles[-1]
        text = await last_bubble.text_content()
        return text.strip() if text else None

    async def get_last_message_info(self):
        await self.page.wait_for_selector(".bubble", timeout=10000)
        bubbles = await self.page.query_selector_all(".bubble")
        if not bubbles:
            return None
        last_bubble = bubbles[-1]
        return await self._bubble_to_message_info(last_bubble)

    async def get_recent_messages_info(self, limit: int = 25) -> list[dict]:
        """Возвращает последние `limit` сообщений (с конца), без None."""
        await self.page.wait_for_selector(".bubble", timeout=10000)
        bubbles = await self.page.query_selector_all(".bubble")
        if not bubbles:
            return []
        tail = bubbles[-max(1, int(limit)) :]
        out: list[dict] = []
        for bubble in tail:
            info = await self._bubble_to_message_info(bubble)
            if info:
                out.append(info)
        return out

    async def _get_editor(self):
        await self.page.wait_for_load_state("domcontentloaded")
        editor = self.page.locator(
            'div.contenteditable[contenteditable][role="textbox"][data-lexical-editor="true"]'
        ).last
        await editor.wait_for(state="visible", timeout=10000)
        return editor

    async def _get_composer(self, timeout_ms: int = 15000):
        await self.page.wait_for_load_state("domcontentloaded")
        deadline = time.monotonic() + (timeout_ms / 1000.0)
        last_error = "composer not found"
        while time.monotonic() < deadline:
            editor = self.page.locator(
                'div.contenteditable[contenteditable][role="textbox"][data-lexical-editor="true"]'
            ).last
            candidates = [
                self.page.locator(
                    "xpath=//div["
                    './/button[@aria-label="Загрузить файл"] and '
                    './/button[@aria-label="Отправить сообщение"] and '
                    './/div[@role="textbox" and @contenteditable]'
                    "]"
                ).last,
                self.page.locator(
                    "xpath=//div["
                    './/div[@role="textbox" and @contenteditable] and '
                    './/input[@type="file"]'
                    "]"
                ).last,
                editor.locator('xpath=ancestor::div[contains(@class, "input")][1]'),
                editor.locator('xpath=ancestor::div[contains(@class, "input")][2]'),
            ]
            for candidate in candidates:
                try:
                    if await candidate.count() == 0:
                        continue
                    if await candidate.first.is_visible():
                        return candidate.first
                except Exception as e:
                    last_error = str(e)
                    continue
            await self.page.wait_for_timeout(250)
        raise TimeoutError(f"failed to resolve composer: {last_error}")

    async def _try_click_send_button(self) -> bool:
        selectors = [
            'button[aria-label="Отправить сообщение"]',
            'button[aria-label*="Отправ"]',
            'button[aria-label*="Send"]',
            'button[title*="Отправ"]',
            'button[title*="Send"]',
            'button:has-text("Отправить")',
            'button:has-text("Send")',
            '[role="button"][aria-label*="Отправ"]',
            '[role="button"][aria-label*="Send"]',
        ]
        for selector in selectors:
            btn = self.page.locator(selector).first
            try:
                if await btn.count() == 0:
                    continue
                if not await btn.is_visible():
                    continue
                if not await btn.is_enabled():
                    continue
                await btn.click(timeout=1500)
                return True
            except Exception:
                continue
        return False

    async def _wait_and_click_send_button(
        self, composer, timeout_ms: int = 12000
    ) -> bool:
        # 1. Кнопка в композере
        primary = composer.locator('button[aria-label="Отправить сообщение"]').first
        if await primary.count() > 0:
            try:
                await primary.wait_for(state="visible", timeout=timeout_ms)
                if await primary.is_enabled():
                    await primary.click()
                    return True
            except Exception:
                pass

        # 2. Кнопка в оверлее (например, после загрузки фото)
        overlay = self.page.locator(
            'div[role="dialog"] button:has-text("Отправить")'
        ).first
        if await overlay.count() > 0 and await overlay.is_visible():
            try:
                await overlay.click()
                return True
            except Exception:
                pass

        # 3. Кнопка в попапе (альтернативный контейнер)
        popup = self.page.locator('.popover button:has-text("Отправить")').first
        if await popup.count() > 0 and await popup.is_visible():
            try:
                await popup.click()
                return True
            except Exception:
                pass

        return False

    async def _get_upload_input(self):
        composer = await self._get_composer()
        # Use input paired with the visible "Загрузить файл" button in current composer.
        upload_input = composer.locator(
            'button[aria-label="Загрузить файл"] + input[type="file"]'
        ).first
        if await upload_input.count() == 0:
            upload_input = composer.locator('input[type="file"][multiple]').first
        await upload_input.wait_for(state="attached", timeout=10000)
        return upload_input

    async def _attach_photo_file(self, composer, photo_path: str) -> None:
        """MAX opens a menu (Фото или видео / Файл / Контакт) on the paperclip click;
        the native file chooser only appears after choosing «Фото или видео»."""
        upload_btn = composer.locator('button[aria-label="Загрузить файл"]').first
        await upload_btn.wait_for(state="visible", timeout=10000)
        file_input = composer.locator('input[type="file"]').first
        await file_input.wait_for(state="attached", timeout=10000)

        async def input_has_files() -> bool:
            return await file_input.evaluate(
                "el => !!(el.files && el.files.length > 0)"
            )

        # 1) Open attachment menu (no filechooser yet)
        await upload_btn.click()
        # Menu lives in .popoverPortal → role=dialog (see debug HTML)
        photo_video = self.page.locator(
            '[role="dialog"] [role="menuitem"][aria-label="Фото или видео"]'
        ).first
        try:
            await photo_video.wait_for(state="visible", timeout=8000)
        except Exception:
            photo_video = self.page.get_by_role("menuitem", name="Фото или видео")
            await photo_video.wait_for(state="visible", timeout=5000)

        # 2) Choosing «Фото или видео» triggers the file chooser
        try:
            async with self.page.expect_file_chooser(timeout=15000) as fc_info:
                await photo_video.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(photo_path)
        except Exception as ex:
            logger.warning(
                f"File chooser after «Фото или видео» failed ({ex}), trying set_input_files"
            )
            await file_input.set_input_files(photo_path)

        if not await input_has_files():
            logger.warning("input still empty; retrying set_input_files")
            await file_input.set_input_files(photo_path)

        if not await input_has_files():
            raise RuntimeError(
                "Photo did not attach: <input type=file> has no files after upload attempts"
            )

    async def _wait_upload_ready(self, timeout_ms: int = 15000) -> None:
        composer = await self._get_composer()
        loader = composer.locator('button[aria-label="Загрузить файл"] .loader').first
        iterations = max(1, timeout_ms // 250)
        for _ in range(iterations):
            try:
                if await loader.count() == 0 or not await loader.is_visible():
                    return
            except Exception:
                return
            await self.page.wait_for_timeout(250)

    async def _close_blocking_popovers(self, timeout_ms: int = 5000) -> None:
        backdrop = self.page.locator(".popoverPortal .backdrop")
        steps = max(1, timeout_ms // 250)
        for _ in range(steps):
            try:
                if await backdrop.count() == 0 or not await backdrop.first.is_visible():
                    return
            except Exception:
                return
            # MAX may keep upload popover open; close it via Escape.
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
            await self.page.wait_for_timeout(250)

    async def send_message(self, text):
        logger.info(f"Sending message: {text[:20]}...")
        editor = await self._get_editor()
        await editor.click()
        try:
            await editor.fill(f"{TELEGRAM_PREFIX} {text}")
        except Exception:
            await self.page.keyboard.insert_text(f"{TELEGRAM_PREFIX} {text}")
        await self.page.keyboard.press("Enter")

    async def debug_screenshot(self, name: str):
        path = f"/tmp/debug_{name}.png"
        await self.page.screenshot(path=path)
        logger.info(f"Screenshot: {path}")

    async def debug_html(self, name: str):
        path = f"/tmp/debug_{name}.html"
        with open(path, "w") as f:
            f.write(await self.page.content())
        logger.info(f"HTML dump: {path}")

    async def download_file(self, url: str) -> bytes:
        """Загружает файл через браузерный контекст (с авторизацией Max)."""
        response = await self.page.context.request.get(url)
        return await response.body()

    async def _attach_document_file(self, composer, file_path: str) -> None:
        """Прикрепляет файл через меню «Файл» (не «Фото или видео»)."""
        upload_btn = composer.locator('button[aria-label="Загрузить файл"]').first
        await upload_btn.wait_for(state="visible", timeout=10000)
        file_input = composer.locator('input[type="file"]').first
        await file_input.wait_for(state="attached", timeout=10000)

        async def input_has_files() -> bool:
            return await file_input.evaluate(
                "el => !!(el.files && el.files.length > 0)"
            )

        await upload_btn.click()
        file_menu_item = self.page.locator(
            '[role="dialog"] [role="menuitem"][aria-label="Файл"]'
        ).first
        try:
            await file_menu_item.wait_for(state="visible", timeout=8000)
        except Exception:
            file_menu_item = self.page.get_by_role("menuitem", name="Файл")
            await file_menu_item.wait_for(state="visible", timeout=5000)

        try:
            async with self.page.expect_file_chooser(timeout=15000) as fc_info:
                await file_menu_item.click()
            file_chooser = await fc_info.value
            await file_chooser.set_files(file_path)
        except Exception as ex:
            logger.warning(
                f"File chooser after «Файл» failed ({ex}), trying set_input_files"
            )
            await file_input.set_input_files(file_path)

        if not await input_has_files():
            logger.warning("input still empty; retrying set_input_files")
            await file_input.set_input_files(file_path)

        if not await input_has_files():
            raise RuntimeError(
                "File did not attach: <input type=file> has no files after upload attempts"
            )

    async def send_file(self, file_path: str, caption: str | None = None) -> None:
        """Отправляет произвольный файл через пункт меню «Файл»."""
        await self.page.wait_for_load_state("domcontentloaded")
        composer = await self._get_composer()
        before_bubbles = await self.page.locator(".bubble").count()

        await self._attach_document_file(composer, file_path)
        await self._wait_upload_ready()
        await self._close_blocking_popovers()

        editor = composer.locator(
            'div.contenteditable[contenteditable][role="textbox"][data-lexical-editor="true"]'
        ).first
        await editor.wait_for(state="visible", timeout=10000)

        try:
            await editor.fill(f"{TELEGRAM_PREFIX} {caption or ''}")
        except Exception:
            try:
                await editor.click(force=True)
            except Exception:
                pass
            await self.page.keyboard.insert_text(caption or "")

        sent = await self._wait_and_click_send_button(composer)
        if sent:
            try:
                await self.page.wait_for_function(
                    "(prev) => document.querySelectorAll('.bubble').length > prev",
                    arg=before_bubbles,
                    timeout=8000,
                )
                logger.info("File send confirmed")
                return
            except Exception as ex:
                logger.warning(f"Send button click did not increase bubble count: {ex}")

        try:
            await editor.click(force=True)
            await self.page.keyboard.press("Enter")
            await self.page.wait_for_function(
                "(prev) => document.querySelectorAll('.bubble').length > prev",
                arg=before_bubbles,
                timeout=8000,
            )
            logger.info("File send confirmed via Enter")
            return
        except Exception as ex:
            logger.warning(f"Enter fallback failed: {ex}")

        logger.error("File send failed: no method worked")

    async def send_photo(self, photo_path: str, caption: str | None = None) -> None:
        await self.page.wait_for_load_state("domcontentloaded")
        composer = await self._get_composer()
        before_bubbles = await self.page.locator(".bubble").count()

        await self._attach_photo_file(composer, photo_path)

        # await self.debug_screenshot("send_photo_1")
        # await self.debug_html("send_photo_1")

        # Ждём появления превью с ПРАВИЛЬНЫМИ селекторами для MAX
        preview_selectors = [
            ".attaches",  # Основной контейнер вложений
            ".attach",  # Контейнер файла
            ".cover",  # Обложка превью
            ".attaches img",  # Изображение в контейнере вложений
            ".file-preview",
            '[data-testid="media-preview"]',
            ".image-preview",
            ".media-preview",
        ]
        preview_found = False
        for selector in preview_selectors:
            try:
                await self.page.wait_for_selector(selector, timeout=3000)
                preview_found = True
                logger.info(f"Preview found with selector: {selector}")
                break
            except Exception:
                continue

        if not preview_found:
            logger.warning(
                "No preview found after upload - но файл может быть загружен"
            )
            # Проверяем, появилась ли скрепка (файл прикреплен, но без превью)
            try:
                await self.page.wait_for_selector(
                    '[aria-label="Удалить вложение"]', timeout=2000
                )
                logger.info("File attached (attachment button found)")
                preview_found = True
            except Exception as ex:
                logger.warning(f"File attached (attachment button not found): {ex}")
                pass

        # await self.debug_screenshot("send_photo_2")
        # await self.debug_html("send_photo_2")

        # Ждём завершения загрузки
        await self._wait_upload_ready()
        await self._close_blocking_popovers()

        # await self.debug_screenshot("send_photo_3")
        # await self.debug_html("send_photo_3")

        # Вставляем подпись, если есть
        editor = composer.locator(
            'div.contenteditable[contenteditable][role="textbox"][data-lexical-editor="true"]'
        ).first
        await editor.wait_for(state="visible", timeout=10000)

        # await self.debug_screenshot("send_photo_4")
        # await self.debug_html("send_photo_4")

        try:
            await editor.fill(f"{TELEGRAM_PREFIX} {caption or ''}")
        except Exception:
            try:
                await editor.click(force=True)
            except Exception:
                pass
            await self.page.keyboard.insert_text(caption or '')

        # await self.debug_screenshot("send_photo_5")
        # await self.debug_html("send_photo_5")

        # Пытаемся отправить кнопкой
        sent = await self._wait_and_click_send_button(composer)

        # await self.debug_screenshot("send_photo_6")
        # await self.debug_html("send_photo_6")

        if sent:
            try:
                # Ждём увеличения количества баблов
                await self.page.wait_for_function(
                    "(prev) => document.querySelectorAll('.bubble').length > prev",
                    arg=before_bubbles,
                    timeout=8000,
                )

                # await self.debug_screenshot("send_photo_7")
                # await self.debug_html("send_photo_7")

                # Проверяем, что превью исчезло
                if preview_found:
                    try:
                        await self.page.wait_for_function(
                            "() => document.querySelector('.attaches, .attach') === null",
                            timeout=5000,
                        )
                        logger.info("Preview disappeared after send")
                    except Exception as ex:
                        logger.warning(f"Preview still present after send: {ex}")

                # await self.debug_screenshot("send_photo_8")
                # await self.debug_html("send_photo_8")

                # Проверяем, что последнее сообщение - фото
                last_info = await self.get_last_message_info()
                has_images = bool(
                    last_info
                    and (
                        last_info.get("type") == "images"
                        or last_info.get("urls")
                    )
                )
                if has_images:
                    logger.info("Photo send confirmed: last message contains image(s)")
                else:
                    logger.warning("Last message does not contain image(s)")

                # await self.debug_screenshot("send_photo_9")
                # await self.debug_html("send_photo_9")

                return

            except Exception as ex:
                logger.warning(f"Send button click did not increase bubble count: {ex}")

        # await self.debug_screenshot("send_photo_10")
        # await self.debug_html("send_photo_10")

        # Fallback: пробуем Enter
        try:
            await editor.click(force=True)
            await self.page.keyboard.press("Enter")
            await self.page.wait_for_function(
                "(prev) => document.querySelectorAll('.bubble').length > prev",
                arg=before_bubbles,
                timeout=8000,
            )
            logger.info("Photo send confirmed via Enter")
            return
        except Exception as ex:
            logger.warning(f"Enter fallback failed: {ex}")

        # await self.debug_screenshot("send_photo_11")
        # await self.debug_html("send_photo_11")

        logger.error("Photo send failed: no method worked")
