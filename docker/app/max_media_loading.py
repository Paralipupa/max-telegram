"""Load MAX's lazy photos before parsing a message (including album tiles)."""
import asyncio
import time

from loguru import logger

PHOTO_NODES = '.media .image-placeholder, .media img:not(.emoji img)'
PHOTO_READY = """node => {
    const img = node.tagName === 'IMG' ? node : node.querySelector('img');
    return !!(img && img.getAttribute('src') &&
        !img.getAttribute('src').startsWith('data:') &&
        img.complete && img.naturalWidth > 0);
}"""


async def photos_ready(bubble):
    for node in await bubble.query_selector_all(PHOTO_NODES):
        if not await node.evaluate(PHOTO_READY):
            return False
    return True


async def load_lazy_photos(bubble, timeout=5.0):
    # Scroll each tile: a tall album need not fit in the viewport as a whole.
    for node in await bubble.query_selector_all(PHOTO_NODES):
        if await node.evaluate(PHOTO_READY):
            continue
        try:
            await node.scroll_into_view_if_needed(timeout=int(timeout * 1000))
            deadline = time.monotonic() + timeout
            while not await node.evaluate(PHOTO_READY):
                if time.monotonic() >= deadline:
                    logger.debug('MAX photo still loading; defer message until next poll')
                    return False
                await asyncio.sleep(0.1)
        except Exception as exc:
            logger.debug('MAX photo unavailable ({}); defer message', type(exc).__name__)
            return False
    return await photos_ready(bubble)
