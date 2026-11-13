import asyncio
import hashlib
import time

from loguru import logger

from browser import BrowserManager
from constants import (
    MAX_MESSAGE_AGE_MINUTES,
    MAX_PREFIX,
    TAIL_LIMIT,
    TELEGRAM_PREFIX,
    ChatPair,
)
from dedup_store import DedupStore
from helpers import strip_trailing_time
from max_client import MaxClient
from telegram_client import (
    TelegramUnauthorizedError,
    send,
    send_document,
    send_media_group,
    send_photo,
    send_video,
)


async def run_bridge(pair: ChatPair, total_pairs: int = 1) -> None:
    logger.info(
        f"[{pair.name}] Запускаем bridge: Max {pair.max_chat_id} → TG {pair.telegram_chat_id}"
    )
    b = await BrowserManager.get(pair.name, pair.max_url)
    maxc = MaxClient(b["page"])

    store = DedupStore(pair.dedup_path)
    while True:
        async with b["lock"]:
            await maxc.ensure_chat(pair.max_chat_id)
            warmed = await _warmup_dedup_if_needed(store, maxc, pair.name, pair.max_chat_id)
        if warmed:
            break
        logger.warning(
            f"[{pair.name}] Дедупликация пока пустая; повторяем прогрев через 10 секунд"
        )
        await asyncio.sleep(10)
    logger.info(f"[{pair.name}] Дедупликация прогрета: {store.count()}. Слушаем сообщения...")
    last_page_reload = time.monotonic()
    PAGE_RELOAD_INTERVAL = (
        30 * 60
    )  # Перезагружать страницу каждые 30 минут (освобождает память SPA)
    poll_interval = (
        total_pairs * 2
    )  # Чем больше пар, тем реже опрашиваем — снижаем нагрузку на CPU

    while True:
        try:
            now = time.monotonic()
            if now - last_page_reload >= PAGE_RELOAD_INTERVAL:
                last_page_reload = now  # обновляем заранее, чтобы не зациклиться при ошибке
                async with b["lock"]:
                    await BrowserManager.reload_page(pair.name)
            async with b["lock"]:
                await maxc.ensure_chat(pair.max_chat_id)
                msgs = await maxc.get_recent_messages_info(limit=TAIL_LIMIT)
                if not maxc.is_chat_url(maxc.page.url, pair.max_chat_id):
                    raise RuntimeError(f"[{pair.name}] MAX переключился на другой чат")
            await _process_messages(store, msgs, maxc, pair)
        except TelegramUnauthorizedError as e:
            logger.error(f"[{pair.name}] {e}. Останавливаем опрос этой пары до перезапуска")
            return
        except Exception as e:
            logger.error(f"[{pair.name}] Ошибка: {e}")
        await asyncio.sleep(poll_interval)


def _format_reply_prefix(msg: dict) -> str:
    """Возвращает строку с цитатой для reply-сообщений, или пустую строку."""
    rq = msg.get("reply_quote")
    if not rq:
        return ""
    author = (rq.get("author") or "").strip()
    text = (rq.get("text") or "").strip()
    if not author and not text:
        return ""
    quote = f"{author}: «{text}»" if author and text else (author or f"«{text}»")
    return f"↩ {quote}\n"


def _format_images_caption(msg: dict) -> str:
    reply = _format_reply_prefix(msg)
    caption = msg.get("caption") or msg.get("text")
    body = f"{reply}{caption}" if caption else f"{reply}[фото]"
    sender = msg.get("sender",{}).get("name") or ""
    return f"{sender}{MAX_PREFIX} {body}"


def _format_attachments_caption(msg: dict) -> str:
    reply = _format_reply_prefix(msg)
    caption = msg.get("caption")
    body = f"{reply}{caption}" if caption else f"{reply}[файл]"
    sender = msg.get("sender",{}).get("name") or ""
    return f"{sender}{MAX_PREFIX} {body}"


async def _download_or_url(maxc: MaxClient, url: str) -> str | bytes:
    """Пробует скачать файл через браузерный контекст Max; при ошибке возвращает URL."""
    try:
        return await maxc.download_file(url)
    except Exception as e:
        logger.warning(f"Не удалось скачать файл {url}, отправляю URL: {e}")
        return url


async def _send_attachments(
    msg: dict, caption: str, maxc: MaxClient, pair: ChatPair
) -> None:
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
            send_video(pair, data, c, filename=name or "video.mp4")
        else:
            send_document(pair, data, c, filename=name or "file")


async def _send_to_telegram(
    msg: dict, message_text: str, maxc: MaxClient, pair: ChatPair
) -> None:
    # await maxc.debug_screenshot("send_to_telegram_1")
    # await maxc.debug_html("send_to_telegram_1")

    if msg["type"] == "images":
        caption = strip_trailing_time(_format_images_caption(msg))
        urls = msg.get("urls") or []
        if len(urls) == 1:
            send_photo(pair, urls[0], caption)
        else:
            send_media_group(pair, urls, caption)
        return

    if msg["type"] == "attachments":
        cap = strip_trailing_time(_format_attachments_caption(msg))
        await _send_attachments(msg, cap, maxc, pair)
        return

    if msg["type"] == "mixed":
        cap_img = strip_trailing_time(_format_images_caption(msg))
        image_urls = msg.get("image_urls") or []
        if len(image_urls) == 1:
            send_photo(pair, image_urls[0], cap_img)
        elif len(image_urls) > 1:
            send_media_group(pair, image_urls, cap_img)
        for item in msg.get("attachments") or []:
            url = item.get("url")
            if not url:
                continue
            name = item.get("name") or ""
            data = await _download_or_url(maxc, url)
            if item.get("kind") == "video":
                send_video(pair, data, None, filename=name or "video.mp4")
            else:
                send_document(pair, data, None, filename=name or "file")
        return
    if message_text:
        reply = _format_reply_prefix(msg)
        sender = msg.get("sender",{}).get("name") or ""
        send(pair, f"{sender}{MAX_PREFIX} {reply}{message_text}")
    else:
        logger.warning(
            f"[{pair.name}] Нет текста в сообщении: {msg} (type={msg['type']})"
        )


def _is_expired(msg: dict) -> bool:
    timestamp = msg.get("timestamp")
    return (
        MAX_MESSAGE_AGE_MINUTES > 0
        and isinstance(timestamp, (int, float))
        and time.time() - timestamp > MAX_MESSAGE_AGE_MINUTES * 60
    )


def _photo_field(msg: dict) -> str | None:
    if msg.get("type") == "images" and msg.get("urls"):
        return "urls"
    if msg.get("type") == "mixed" and msg.get("image_urls"):
        return "image_urls"
    return None


def _photo_message_context(msg: dict) -> str:
    caption = strip_trailing_time(msg.get("caption") or msg.get("text") or "").strip()
    caption_hash = hashlib.sha256(caption.encode("utf-8")).hexdigest()
    outgoing = bool((msg.get("sender") or {}).get("is_outgoing"))
    return f"{msg.get('timestamp')}:{int(outgoing)}:{caption_hash}"


async def _photo_content_fingerprint(
    msg: dict, field: str, context: str, maxc: MaxClient
) -> str:
    hashes = [
        hashlib.sha256(await maxc.download_file(url)).hexdigest() for url in msg[field]
    ]
    fingerprint, _ = DedupStore.fingerprint({**msg, field: hashes})
    return f"photo-content:{context}:{fingerprint}"


async def _warmup_dedup_if_needed(
    store: DedupStore, maxc: MaxClient, pair_name: str, chat_id: str
) -> bool:
    if store.count() != 0:
        return True
    try:
        warm = await maxc.get_recent_messages_info(limit=TAIL_LIMIT * 3)
        if not maxc.is_chat_url(maxc.page.url, chat_id):
            raise RuntimeError("MAX покинул открытый чат во время прогрева")
        fingerprints = []
        for msg in warm:
            fp, text = store.fingerprint(msg)
            field = _photo_field(msg)
            if TELEGRAM_PREFIX in text:
                continue
            if not field:
                fingerprints.append(fp)
                continue
            context = _photo_message_context(msg)
            fingerprints.append(f"photo-url:{context}:{fp}")
            if not _is_expired(msg):
                try:
                    content_key = await _photo_content_fingerprint(
                        msg, field, context, maxc
                    )
                    fingerprints.append(content_key)
                except Exception as e:
                    logger.warning(
                        f"[{pair_name}] Не удалось проверить фото при прогреве: "
                        f"{type(e).__name__}"
                    )
        if fingerprints:
            store.add(*fingerprints)
        return True
    except Exception as e:
        logger.error(f"[{pair_name}] Ошибка прогрева дедупа: {e}")
        return False


async def _process_messages(
    store: DedupStore,
    msgs: list[dict],
    maxc: MaxClient,
    pair: ChatPair,
) -> None:
    for msg in reversed(msgs):
        fp, text = store.fingerprint(msg)
        if TELEGRAM_PREFIX in text:
            continue
        field = _photo_field(msg)
        context = _photo_message_context(msg) if field else ""
        url_key = f"photo-url:{context}:{fp}" if field else fp
        if store.has(url_key):
            continue

        if _is_expired(msg):
            logger.info(
                f"[{pair.name}] Пропускаем сообщение MAX старше "
                f"{MAX_MESSAGE_AGE_MINUTES} минут: {text[:60]}"
            )
            store.add(url_key)
            continue

        content_key = None
        if field:
            try:
                content_key = await _photo_content_fingerprint(msg, field, context, maxc)
            except Exception as e:
                logger.warning(
                    f"[{pair.name}] Не удалось проверить содержимое фото MAX: "
                    f"{type(e).__name__}. Повторим при следующем опросе."
                )
                continue
            if store.has(content_key) or store.has(fp):
                store.add(url_key, content_key)
                continue

        try:
            message_text = msg.get("text") or msg.get("caption") or ""
            message_text = strip_trailing_time(message_text)
            await _send_to_telegram(msg, message_text, maxc, pair)
        except TelegramUnauthorizedError:
            raise
        except Exception as e:
            logger.error(f"[{pair.name}] Ошибка при отправке сообщения: {e}")
            continue
        if content_key:
            store.add(url_key, content_key)
        else:
            store.add(url_key)
