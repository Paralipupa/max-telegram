import ast
import json
import tempfile
from types import SimpleNamespace
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

    async def test_wait_timeout_saves_page_and_preserves_exception(self):
        # Load the actual polling method without requiring a browser installation.
        source = Path(__file__).resolve().parents[1] / 'app' / 'max_client.py'
        tree = ast.parse(source.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'MaxClient')
        method = next(n for n in cls.body if isinstance(n, ast.AsyncFunctionDef)
                      and n.name == 'get_recent_messages_info')
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
        with tempfile.TemporaryDirectory() as tmp, patch.dict('os.environ', {
            'MAX_MEDIA_DEBUG': 'true', 'MAX_MEDIA_DEBUG_DIR': tmp,
        }):
            page = AsyncMock()
            page.url = 'https://web.max.ru/login'
            page.content.return_value = '<html>Login screen</html>'
            error = TimeoutError('waiting for .bubble')
            page.wait_for_selector.side_effect = error
            debug = MediaDebug()
            client = SimpleNamespace(page=page, media_debug=debug)
            with self.assertRaises(TimeoutError) as raised:
                await namespace['get_recent_messages_info'](client)
            self.assertIs(raised.exception, error)
            files = list(Path(tmp).rglob('*.json'))
            self.assertEqual(len(files), 1)
            data = json.loads(files[0].read_text())
            self.assertEqual(data['reason'], 'bubble_wait_failed:TimeoutError')
            self.assertEqual(data['page_url'], page.url)
            self.assertEqual(data['messages'], [])
            self.assertEqual(files[0].with_suffix('.html').read_text(), page.content.return_value)
            page.screenshot.assert_awaited_once()
            # A different screen without bubbles should also produce a snapshot.
            debug.last_attempt = None
            page.content.return_value = '<html>Loading chat</html>'
            await debug.capture(page, [], [], reason='bubble_wait_failed:TimeoutError')
            self.assertEqual(len(list(Path(tmp).rglob('*.json'))), 2)

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
