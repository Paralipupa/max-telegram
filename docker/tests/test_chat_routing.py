import unittest
from unittest.mock import AsyncMock, Mock, patch

from browser import BrowserManager
from bridge import _process_messages, _warmup_dedup_if_needed
from constants import ChatPair
from max_client import MaxClient
from processing import process
from telegram_client import TelegramUnauthorizedError, send
from telegram_webhook import check_bot_visibility, ensure_webhook, webhook_base_url


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

    async def test_messages_from_other_bots_are_not_forwarded_to_max(self):
        with patch("processing._process_single_message", new_callable=AsyncMock) as handle:
            await process({"message": {
                "chat": {"id": -456}, "from": {"is_bot": True}, "text": "spam"
            }}, PAIR)
            handle.assert_not_awaited()

    async def test_telegram_api_rejection_is_not_reported_as_delivery(self):
        response = Mock(status_code=400)
        response.json.return_value = {"ok": False, "description": "chat not found"}
        with patch("telegram_client.requests.post", return_value=response) as post:
            with self.assertRaisesRegex(RuntimeError, "chat not found"):
                send(PAIR, "test")
            self.assertEqual(post.call_args.kwargs["json"]["chat_id"], "-456")

    async def test_successful_send_reports_telegram_message_id(self):
        response = Mock(status_code=200)
        response.json.return_value = {
            "ok": True, "result": {"message_id": 123, "from": {"username": "bridge_bot"}}
        }
        with patch("telegram_client.requests.post", return_value=response), \
             patch("telegram_client.logger.info") as log:
            send(PAIR, "test")
            self.assertIn("message_id=123", log.call_args.args[0])
            self.assertIn("bot=bridge_bot", log.call_args.args[0])

    async def test_unauthorized_token_does_not_retry_each_poll(self):
        response = Mock(status_code=401)
        response.json.return_value = {"ok": False, "description": "Unauthorized"}
        with patch("telegram_client.requests.post", return_value=response):
            with self.assertRaises(TelegramUnauthorizedError):
                send(PAIR, "test")

        store = Mock()
        store.fingerprint.return_value = ("fingerprint", "message")
        store.has.return_value = False
        with patch("bridge._send_to_telegram", new_callable=AsyncMock) as deliver:
            deliver.side_effect = TelegramUnauthorizedError("Unauthorized")
            with self.assertRaises(TelegramUnauthorizedError):
                await _process_messages(
                    store, [{"type": "text", "text": "message"}], 0, Mock(), PAIR
                )
        store.add.assert_not_called()

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


class WebhookSetupTests(unittest.TestCase):
    def test_current_host_is_used_and_existing_webhook_is_preserved(self):
        with patch.dict("os.environ", {"VIRTUAL_HOST": "bridge.example.org"}):
            self.assertEqual(webhook_base_url(), "https://bridge.example.org")
        expected = f"https://bridge.example.org{PAIR.webhook_path}"
        with patch("telegram_webhook._post_telegram", return_value={"url": expected}) as post:
            self.assertFalse(ensure_webhook(PAIR, "https://bridge.example.org"))
            post.assert_called_once_with(PAIR, "getWebhookInfo")

    def test_missing_webhook_is_registered_without_dropping_updates(self):
        with patch("telegram_webhook._post_telegram", side_effect=[{"url": ""}, True]) as post:
            self.assertTrue(ensure_webhook(PAIR, "https://bridge.example.org"))
            self.assertEqual(post.call_args.kwargs["json"], {
                "url": f"https://bridge.example.org{PAIR.webhook_path}",
                "allowed_updates": [],
            })

    def test_existing_webhook_with_messages_disabled_is_repaired(self):
        expected = f"https://bridge.example.org{PAIR.webhook_path}"
        info = {"url": expected, "allowed_updates": ["callback_query"]}
        with patch("telegram_webhook._post_telegram", side_effect=[info, True]) as post:
            self.assertTrue(ensure_webhook(PAIR, "https://bridge.example.org"))
            self.assertEqual(post.call_args.kwargs["json"], {
                "url": expected,
                "allowed_updates": ["callback_query", "message"],
            })

    def test_webhook_on_another_host_is_not_replaced(self):
        with patch("telegram_webhook._post_telegram", return_value={"url": "https://other.example.org/bot"}) as post:
            with self.assertRaisesRegex(RuntimeError, "другой хост"):
                ensure_webhook(PAIR, "https://bridge.example.org")
            post.assert_called_once()

    def test_privacy_mode_warning_for_non_admin_group_bot(self):
        responses = [
            {"id": 123, "username": "bridge_bot", "can_read_all_group_messages": False},
            {"type": "supergroup"},
            {"status": "member"},
        ]
        with patch("telegram_webhook._post_telegram", side_effect=responses), \
                patch("telegram_webhook.logger.warning") as warning:
            check_bot_visibility(PAIR)
            self.assertIn("privacy mode", warning.call_args.args[0])

    def test_admin_group_bot_does_not_trigger_privacy_warning(self):
        responses = [
            {"id": 123, "username": "bridge_bot", "can_read_all_group_messages": False},
            {"type": "supergroup"},
            {"status": "administrator"},
        ]
        with patch("telegram_webhook._post_telegram", side_effect=responses), \
                patch("telegram_webhook.logger.warning") as warning:
            check_bot_visibility(PAIR)
            warning.assert_not_called()


if __name__ == "__main__":
    unittest.main()
