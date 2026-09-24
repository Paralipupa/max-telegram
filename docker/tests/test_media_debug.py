import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from media_debug import MediaDebug


class MediaDebugTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_throttle_change_and_retention(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {
            'MAX_MEDIA_DEBUG': 'true', 'MAX_MEDIA_DEBUG_DIR': tmp,
            'MAX_MEDIA_DEBUG_KEEP': '2', 'MAX_MEDIA_DEBUG_INTERVAL': '60',
        }):
            debug = MediaDebug()
            page = AsyncMock()
            page.url = 'https://web.max.ru/test'
            page.content.return_value = '<html>snapshot</html>'
            bubble = AsyncMock()
            bubble.evaluate.return_value = {'html': '<video/>', 'text': '05:21 AM',
                                             'media': [{'tag': 'VIDEO', 'src': 'blob:test'}]}
            parsed = [{'type': 'text', 'text': '05:21 AM'}]
            await debug.capture(page, [bubble], parsed)
            files = list(Path(tmp).rglob('*.json'))
            self.assertEqual(len(files), 1)
            self.assertIn('text_with_media_candidates', files[0].read_text())
            await debug.capture(page, [bubble], parsed)
            self.assertEqual(bubble.evaluate.await_count, 1)
            debug.last_attempt = None
            await debug.capture(page, [bubble], parsed)
            self.assertEqual(page.content.await_count, 1)
            for text in ('05:22 AM', '05:23 AM'):
                debug.last_attempt = None
                bubble.evaluate.return_value['text'] = text
                await debug.capture(page, [bubble], parsed)
            self.assertEqual(len(list(Path(tmp).rglob('*.json'))), 2)
            self.assertEqual(len(list(Path(tmp).rglob('*.html'))), 2)

    async def test_disabled_and_failures_do_not_interrupt(self):
        debug = MediaDebug()
        page = AsyncMock()
        bubble = AsyncMock()
        debug.enabled = False
        await debug.capture(page, [bubble], [None])
        bubble.evaluate.assert_not_awaited()
        debug.enabled = True
        bubble.evaluate.side_effect = RuntimeError('detached')
        await debug.capture(page, [bubble], [None])
        bubble.evaluate.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
