import unittest
from unittest.mock import AsyncMock, Mock, patch

from browser import BrowserManager
from bridge import _process_messages, _warmup_dedup_if_needed
from constants import ChatPair
from max_client import MaxClient
from processing import process
from telegram_client import send


PAIR = ChatPair("тест", "-123", "token", "-456")


class MaxRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_chat_rejects_redirect_to_chat_list(self):
        page = Mock()
        page.url = "https://web.max.ru/"
        page.goto = AsyncMock()
        page.wait_for_selector = AsyncMock(side_effect=TimeoutError())

        with self.assertRaisesRegex(RuntimeError, "Чат MAX -123 не открылся"):
            await MaxClient(page).open_chat(PAIR.max_chat_id)
        page.goto.assert_awaited_once_with(
            "https://web.max.ru/-123", wait_until="domcontentloaded", timeout=60000
        )

    async def test_open_chat_accepts_only_target_chat(self):
        page = Mock()
        page.url = "https://web.max.ru/"
        page.goto = AsyncMock()
        page.wait_for_selector = AsyncMock()

        async def navigate(*args, **kwargs):
            page.url = "https://web.max.ru/-123"

        page.goto.side_effect = navigate
        await MaxClient(page).open_chat(PAIR.max_chat_id)
        page.wait_for_selector.assert_awaited_once()

        page.url = "https://web.max.ru/-999"
        page.goto.reset_mock()
        async def wrong_chat(*args, **kwargs):
            page.url = "https://web.max.ru/-999"
        page.goto.side_effect = wrong_chat
        with self.assertRaisesRegex(RuntimeError, "Вместо чата MAX -123"):
            await MaxClient(page).open_chat(PAIR.max_chat_id)

    async def test_browser_manager_uses_chat_id_from_configured_url(self):
        page = Mock()
        with patch("browser.MaxClient") as client:
            client.return_value.open_chat = AsyncMock()
            await BrowserManager._goto(page, PAIR.name, PAIR.max_url)
            client.return_value.open_chat.assert_awaited_once_with("-123")


class TelegramRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_configured_telegram_chat_is_processed(self):
        with patch("processing._process_single_message", new_callable=AsyncMock) as handle:
            await process({"message": {"chat": {"id": -999}, "text": "wrong"}}, PAIR)
            handle.assert_not_awaited()
            await process({"message": {"chat": {"id": -456}, "text": "right"}}, PAIR)
            handle.assert_awaited_once()

    async def test_telegram_api_rejection_is_not_reported_as_delivery(self):
        response = Mock(status_code=400)
        response.json.return_value = {"ok": False, "description": "chat not found"}
        with patch("telegram_client.requests.post", return_value=response) as post:
            with self.assertRaisesRegex(RuntimeError, "chat not found"):
                send(PAIR, "test")
            self.assertEqual(post.call_args.kwargs["json"]["chat_id"], "-456")

    async def test_failed_delivery_remains_available_for_retry(self):
        store = Mock()
        store.fingerprint.return_value = ("fingerprint", "message")
        store.has.return_value = False
        with patch("bridge._send_to_telegram", new_callable=AsyncMock) as deliver:
            deliver.side_effect = RuntimeError("Unauthorized")
            count = await _process_messages(
                store, [{"type": "text", "text": "message"}], 0, Mock(), PAIR
            )
        self.assertEqual(count, 0)
        store.add.assert_not_called()

    async def test_empty_max_chat_finishes_warmup(self):
        store = Mock()
        store.count.return_value = 0
        max_client = Mock()
        max_client.page.url = PAIR.max_url
        max_client.get_recent_messages_info = AsyncMock(return_value=[])
        max_client.is_chat_url.return_value = True
        self.assertTrue(
            await _warmup_dedup_if_needed(store, max_client, PAIR.name, PAIR.max_chat_id)
        )


if __name__ == "__main__":
    unittest.main()
