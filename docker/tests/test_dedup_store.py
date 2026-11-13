import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from bridge import _process_messages, _warmup_dedup_if_needed
from constants import ChatPair
from dedup_store import DedupStore


class MediaFingerprintTests(unittest.TestCase):
    def test_photos_with_same_visible_time_have_different_fingerprints(self):
        first = {
            "type": "images",
            "caption": "02:20 PM",
            "urls": ["https://i.oneme.ru/i?r=photo-one&expires=100"],
        }
        second = {
            "type": "images",
            "caption": "02:20 PM",
            "urls": ["https://i.oneme.ru/i?r=photo-two&expires=100"],
        }
        self.assertNotEqual(
            DedupStore.fingerprint(first)[0], DedupStore.fingerprint(second)[0]
        )

    def test_changed_expiry_does_not_resend_the_same_photo(self):
        first = {
            "type": "images",
            "caption": "02:20 PM",
            "urls": ["https://i.oneme.ru/i?r=photo-one&expires=100"],
        }
        refreshed = {
            "type": "images",
            "caption": "02:21 PM",
            "urls": ["https://i.oneme.ru/i?expires=200&r=photo-one"],
        }
        self.assertEqual(
            DedupStore.fingerprint(first)[0], DedupStore.fingerprint(refreshed)[0]
        )

    def test_text_fingerprint_stays_compatible_with_existing_store(self):
        message = {"type": "text", "text": "обычный текст 02:20 PM"}
        expected = hashlib.sha256(message["text"][:30].encode()).hexdigest()
        self.assertEqual(DedupStore.fingerprint(message)[0], expected)


class ConsecutivePhotoDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_photo_in_same_minute_is_delivered(self):
        first = {
            "type": "images",
            "caption": "02:20 PM",
            "urls": ["https://i.oneme.ru/i?r=photo-one&expires=100"],
        }
        second = {
            "type": "images",
            "caption": "02:20 PM",
            "urls": ["https://i.oneme.ru/i?r=photo-two&expires=100"],
        }
        pair = ChatPair("тест", "-123", "token", "-456")
        maxc = Mock(download_file=AsyncMock(side_effect=lambda url: url.encode()))
        with tempfile.TemporaryDirectory() as directory:
            store = DedupStore(str(Path(directory) / "dedup.sqlite3"))
            with patch("bridge.send_photo") as send_photo:
                await _process_messages(store, [first], maxc, pair)
                await _process_messages(store, [first, second], maxc, pair)
            self.assertEqual(
                [call.args[1] for call in send_photo.call_args_list],
                [first["urls"][0], second["urls"][0]],
            )

    async def test_rotated_photo_url_is_deduplicated_after_restart(self):
        first = {
            "type": "images",
            "timestamp": time.time() - 65,
            "urls": ["https://i.oneme.ru/i?r=initial&expires=100"],
        }
        refreshed = {**first, "urls": ["https://i.oneme.ru/i?r=rotated&expires=200"]}
        reposted = {**refreshed, "timestamp": first["timestamp"] + 60}
        pair = ChatPair("тест", "-123", "token", "-456")
        maxc = Mock(download_file=AsyncMock(return_value=b"same photo"))

        with tempfile.TemporaryDirectory() as directory, patch(
            "bridge.send_photo"
        ) as send_photo:
            path = str(Path(directory) / "dedup.sqlite3")
            store = DedupStore(path)
            await _process_messages(store, [first], maxc, pair)

            store = DedupStore(path)
            await _process_messages(store, [refreshed], maxc, pair)
            send_photo.assert_called_once()

            await _process_messages(store, [refreshed], maxc, pair)
            self.assertEqual(maxc.download_file.await_count, 2)

            await _process_messages(store, [reposted], maxc, pair)
            self.assertEqual(send_photo.call_count, 2)

    async def test_legacy_url_seeds_content_fingerprint(self):
        first = {"type": "images", "urls": ["https://i.oneme.ru/i?r=initial"]}
        refreshed = {**first, "urls": ["https://i.oneme.ru/i?r=rotated"]}
        pair = ChatPair("тест", "-123", "token", "-456")
        maxc = Mock(download_file=AsyncMock(return_value=b"same photo"))

        with tempfile.TemporaryDirectory() as directory, patch(
            "bridge.send_photo"
        ) as send_photo:
            store = DedupStore(str(Path(directory) / "dedup.sqlite3"))
            store.add(DedupStore.fingerprint(first)[0])
            await _process_messages(store, [first], maxc, pair)
            await _process_messages(store, [refreshed], maxc, pair)

        send_photo.assert_not_called()

    async def test_photo_retries_after_download_failure(self):
        message = {"type": "images", "urls": ["https://i.oneme.ru/i?r=photo"]}
        pair = ChatPair("тест", "-123", "token", "-456")
        maxc = Mock(download_file=AsyncMock(side_effect=[TimeoutError(), b"photo"]))

        with tempfile.TemporaryDirectory() as directory, patch(
            "bridge.send_photo"
        ) as send_photo:
            store = DedupStore(str(Path(directory) / "dedup.sqlite3"))
            await _process_messages(store, [message], maxc, pair)
            self.assertEqual(store.count(), 0)
            send_photo.assert_not_called()

            await _process_messages(store, [message], maxc, pair)
            send_photo.assert_called_once()

    async def test_warmup_deduplicates_existing_photo_with_a_new_url(self):
        first = {"type": "images", "urls": ["https://i.oneme.ru/i?r=initial"]}
        refreshed = {**first, "urls": ["https://i.oneme.ru/i?r=rotated"]}
        pair = ChatPair("тест", "-123", "token", "-456")
        maxc = Mock(
            download_file=AsyncMock(return_value=b"same photo"),
            get_recent_messages_info=AsyncMock(return_value=[first]),
        )
        maxc.is_chat_url.return_value = True

        with tempfile.TemporaryDirectory() as directory, patch(
            "bridge.send_photo"
        ) as send_photo:
            store = DedupStore(str(Path(directory) / "dedup.sqlite3"))
            self.assertTrue(
                await _warmup_dedup_if_needed(store, maxc, pair.name, pair.max_chat_id)
            )
            await _process_messages(store, [refreshed], maxc, pair)

        send_photo.assert_not_called()

    async def test_old_photo_is_skipped_without_downloading(self):
        message = {
            "type": "images",
            "timestamp": time.time() - 31 * 60,
            "urls": ["https://i.oneme.ru/i?r=rotated"],
        }
        pair = ChatPair("тест", "-123", "token", "-456")
        maxc = Mock(download_file=AsyncMock())

        with (
            tempfile.TemporaryDirectory() as directory,
            patch("bridge.MAX_MESSAGE_AGE_MINUTES", 30),
            patch("bridge.send_photo") as send_photo,
        ):
            store = DedupStore(str(Path(directory) / "dedup.sqlite3"))
            await _process_messages(store, [message], maxc, pair)

        maxc.download_file.assert_not_awaited()
        send_photo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
