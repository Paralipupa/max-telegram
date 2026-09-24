import unittest
from unittest.mock import AsyncMock, patch

from max_media_loading import load_lazy_photos
from max_message_info import bubble_to_message_info


class LazyPhotosTests(unittest.IsolatedAsyncioTestCase):
    async def test_scroll_each_unloaded_album_tile(self):
        a, b = AsyncMock(), AsyncMock()
        a.evaluate.side_effect = [False, True, True]
        b.evaluate.side_effect = [False, True, True]
        bubble = AsyncMock()
        bubble.query_selector_all.return_value = [a, b]
        self.assertTrue(await load_lazy_photos(bubble))
        a.scroll_into_view_if_needed.assert_awaited_once()
        b.scroll_into_view_if_needed.assert_awaited_once()

    async def test_loaded_image_is_not_scrolled(self):
        node = AsyncMock()
        node.evaluate.return_value = True
        bubble = AsyncMock()
        bubble.query_selector_all.return_value = [node]
        self.assertTrue(await load_lazy_photos(bubble))
        node.scroll_into_view_if_needed.assert_not_awaited()

    async def test_pending_photo_not_parsed_as_time_or_partial_album(self):
        node = AsyncMock()
        node.evaluate.return_value = False
        bubble = AsyncMock()
        bubble.query_selector_all.return_value = [node]
        self.assertFalse(await load_lazy_photos(bubble, timeout=0))
        with patch('max_message_info.extract_image_urls', new_callable=AsyncMock) as extract:
            self.assertIsNone(await bubble_to_message_info(bubble))
            extract.assert_not_awaited()

    async def test_detached_tile_is_retried_later(self):
        node = AsyncMock()
        node.evaluate.return_value = False
        node.scroll_into_view_if_needed.side_effect = RuntimeError('detached')
        bubble = AsyncMock()
        bubble.query_selector_all.return_value = [node]
        self.assertFalse(await load_lazy_photos(bubble))
