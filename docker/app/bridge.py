import asyncio
import time
from constants import MAX_PREFIX, TELEGRAM_PREFIX
from helpers import strip_trailing_time
from browser import BrowserManager
from max_client import MaxClient
from telegram_client import (
    send,
    send_document,
    send_media_group,
    send_photo,
    send_video,
)
from dedup_store import DedupStore
from loguru import logger
import os
from constants import TAIL_LIMIT

async def run_bridge():
    logger.info("Запускаем bridge")
    b = await BrowserManager.get()
    page = b["page"]
    maxc = MaxClient(page)

    store = DedupStore()
    await _warmup_dedup_if_needed(store, maxc)
    seen_count = store.count()
    last_count_refresh = time.monotonic()

    logger.info(f"Дедупликация прогрета: {seen_count}. Слушаем сообщения...")
    while True:
        try:
            seen_count, last_count_refresh = _refresh_seen_count_if_needed(
                store, seen_count, last_count_refresh
            )
            async with BrowserManager.lock:
                msgs = await maxc.get_recent_messages_info(
                    limit=_dynamic_tail_limit(seen_count)
                )
            seen_count = await _process_messages(store, msgs, seen_count, maxc)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
        await asyncio.sleep(1)


def _format_images_caption(msg: dict) -> str:
    caption = msg.get("caption")
    return f"{MAX_PREFIX} {caption}" if caption else f"{MAX_PREFIX} [фото]"


def _format_attachments_caption(msg: dict) -> str:
    caption = msg.get("caption")
    return f"{MAX_PREFIX} {caption}" if caption else f"{MAX_PREFIX} [файл]"



async def _download_or_url(maxc: MaxClient, url: str) -> str | bytes:
    """Пробует скачать файл через браузерный контекст Max; при ошибке возвращает URL."""
    try:
        return await maxc.download_file(url)
    except Exception as e:
        logger.warning(f"Не удалось скачать файл {url}, отправляю URL: {e}")
        return url


async def _send_attachments(msg: dict, caption: str, maxc: MaxClient) -> None:
    items = msg.get("items") or []
    cap = strip_trailing_time(caption)
    for i, item in enumerate(items):
        url = item.get("url")
        if not url:
            continue
        c = cap if i == 0 else None
        name = item.get("name") or ""
        data = await _download_or_url(maxc, url)
        if item.get("kind") == "video":
            send_video(data, c, filename=name or "video.mp4")
        else:
            send_document(data, c, filename=name or "file")


async def _send_to_telegram(msg: dict, message_text: str, maxc: MaxClient) -> None:
    if msg["type"] == "images":
        caption = _format_images_caption(msg)
        caption = strip_trailing_time(caption)
        urls = msg.get("urls") or []
        if len(urls) == 1:
            send_photo(urls[0], caption)
        else:
            send_media_group(urls, caption)
        return

    if msg["type"] == "attachments":
        cap = _format_attachments_caption(msg)
        cap = strip_trailing_time(cap)
        await _send_attachments(msg, cap, maxc)
        return

    if msg["type"] == "mixed":
        cap_img = strip_trailing_time(_format_images_caption(msg))
        image_urls = msg.get("image_urls") or []
        if len(image_urls) == 1:
            send_photo(image_urls[0], cap_img)
        elif len(image_urls) > 1:
            send_media_group(image_urls, cap_img)
        for item in msg.get("attachments") or []:
            url = item.get("url")
            if not url:
                continue
            name = item.get("name") or ""
            data = await _download_or_url(maxc, url)
            if item.get("kind") == "video":
                send_video(data, None, filename=name or "video.mp4")
            else:
                send_document(data, None, filename=name or "file")
        return

    send(f"{MAX_PREFIX} {message_text}")


def _refresh_seen_count_if_needed(
    store: DedupStore,
    seen_count: int,
    last_count_refresh: float,
    interval_sec: float = 5.0,
) -> tuple[int, float]:
    now = time.monotonic()
    if now - last_count_refresh >= interval_sec:
        return store.count(), now
    return seen_count, last_count_refresh


def _dynamic_tail_limit(seen_count: int, tail_limit: int = TAIL_LIMIT) -> int:
    return min(tail_limit, max(1, seen_count))


async def _warmup_dedup_if_needed(store: DedupStore, maxc: MaxClient) -> None:
    if store.count() != 0:
        return
    try:
        warm = await maxc.get_recent_messages_info(limit=TAIL_LIMIT)
        for msg in warm:
            store.add(store.fingerprint(msg))
    except Exception as e:
        logger.error(f"Ошибка прогрева дедупа: {e}")


async def _process_messages(
    store: DedupStore,
    msgs: list[dict],
    seen_count: int,
    maxc: MaxClient,
) -> int:
    for msg in reversed(msgs):
        message_text = msg.get("text") or msg.get("caption") or ""
        message_text = strip_trailing_time(message_text)
        if TELEGRAM_PREFIX in message_text:
            continue
        fp = store.fingerprint(msg)
        if store.has(fp):
            continue

        await _send_to_telegram(msg, message_text, maxc)

        store.add(fp)
        logger.info(f"Отправлено сообщение: {message_text} - {fp}")
        seen_count += 1
    return seen_count
