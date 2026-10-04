import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from bridge import _process_messages
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
        self.assertNotEqual(DedupStore.fingerprint(first)[0], DedupStore.fingerprint(second)[0])

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
        self.assertEqual(DedupStore.fingerprint(first)[0], DedupStore.fingerprint(refreshed)[0])

    def test_text_fingerprint_stays_compatible_with_existing_store(self):
        message = {"type": "text", "text": "обычный текст 02:20 PM"}
        expected = hashlib.sha256(message["text"][:30].encode()).hexdigest()
        self.assertEqual(DedupStore.fingerprint(message)[0], expected)


class ConsecutivePhotoDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_photo_in_same_minute_is_delivered(self):
        first = {
            "type": "images", "caption": "02:20 PM",
            "urls": ["https://i.oneme.ru/i?r=photo-one&expires=100"],
        }
        second = {
            "type": "images", "caption": "02:20 PM",
            "urls": ["https://i.oneme.ru/i?r=photo-two&expires=100"],
        }
        pair = ChatPair("тест", "-123", "token", "-456")
        with tempfile.TemporaryDirectory() as directory:
            store = DedupStore(str(Path(directory) / "dedup.sqlite3"))
            with patch("bridge.send_photo") as send_photo:
                count = await _process_messages(store, [first], 0, Mock(), pair)
                count = await _process_messages(store, [first, second], count, Mock(), pair)
            self.assertEqual(count, 2)
            self.assertEqual([call.args[1] for call in send_photo.call_args_list], [
                first["urls"][0], second["urls"][0],
            ])


if __name__ == "__main__":
    unittest.main()
