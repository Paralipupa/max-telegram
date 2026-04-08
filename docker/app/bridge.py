import asyncio
import os
import time
from constants import MAX_PREFIX, TELEGRAM_PREFIX, TAIL_LIMIT, ChatPair
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


async def run_bridge(pair: ChatPair, total_pairs: int = 1) -> None:
    logger.info(
        f"[{pair.name}] Запускаем bridge: Max {pair.max_chat_id} → TG {pair.telegram_chat_id}"
    )
    b = await BrowserManager.get(pair.name, pair.max_url)
    maxc = MaxClient(b["page"])

    store = DedupStore(pair.dedup_path)
    await _warmup_dedup_if_needed(store, maxc)
    seen_count = store.count()
    if seen_count == 0:
        logger.info(
            f"[{pair.name}] Дедупликация пустая: {seen_count}. Завершаем bridge."
        )
        raise SystemExit(f"[{pair.name}] Bridge завершён: дедупликация пустая")
    last_count_refresh = time.monotonic()

    logger.info(
        f"[{pair.name}] Дедупликация прогрета: {seen_count}. Слушаем сообщения..."
    )
    last_page_reload = time.monotonic()
    PAGE_RELOAD_INTERVAL = (
        30 * 60
    )  # Перезагружать страницу каждые 30 минут (освобождает память SPA)
    poll_interval = (
        total_pairs * 2
    )  # Чем больше пар, тем реже опрашиваем — снижаем нагрузку на CPU

    while True:
        try:
            seen_count, last_count_refresh = _refresh_seen_count_if_needed(
                store, seen_count, last_count_refresh
            )
            now = time.monotonic()
            if now - last_page_reload >= PAGE_RELOAD_INTERVAL:
                last_page_reload = now  # обновляем заранее, чтобы не зациклиться при ошибке
                async with b["lock"]:
                    # logger.info(
                    #     f"[{pair.name}] Перезагружаем страницу браузера для освобождения памяти"
                    # )
                    try:
                        await BrowserManager.reload_page(pair.name)
                    except Exception as reload_err:
                        logger.error(
                            f"[{pair.name}] Страница недоступна после перезагрузки "
                            f"(возможно, требуется авторизация): {reload_err}"
                        )
                        logger.warning(
                            f"[{pair.name}] Принудительно сбрасываем дедупликацию "
                            f"и проверяем доступность страницы..."
                        )
                        try:
                            os.remove(pair.dedup_path)
                            logger.info(
                                f"[{pair.name}] БД дедупликации удалена: {pair.dedup_path}"
                            )
                        except FileNotFoundError:
                            pass
                        store = DedupStore(pair.dedup_path)
                        try:
                            warm = await maxc.get_recent_messages_info(limit=30)
                            for msg in warm:
                                fp, text = store.fingerprint(msg)
                                logger.info(f" warmup fingerprint --> {fp} text --> {text[:30]}")
                                store.add(fp)
                            seen_count = store.count()
                            logger.info(
                                f"[{pair.name}] Прогрев после сброса успешен: {seen_count} записей"
                            )
                        except Exception as warmup_err:
                            logger.error(
                                f"[{pair.name}] Страница всё ещё недоступна: {warmup_err}. "
                                f"Завершаем bridge."
                            )
                            raise SystemExit(
                                f"[{pair.name}] Bridge завершён: авторизация недействительна"
                            ) from warmup_err
            async with b["lock"]:
                msgs = await maxc.get_recent_messages_info(
                    limit=_dynamic_tail_limit(seen_count)
                )
            seen_count = await _process_messages(store, msgs, seen_count, maxc, pair)
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
        count = 30
        warm = await maxc.get_recent_messages_info(limit=count)
        for msg in warm:
            fp, text = store.fingerprint(msg)
            logger.info(f" warmup fingerprint --> {fp} text --> {text[:30]}")
            store.add(fp)
    except Exception as e:
        logger.error(f"Ошибка прогрева дедупа: {e}")


async def _process_messages(
    store: DedupStore,
    msgs: list[dict],
    seen_count: int,
    maxc: MaxClient,
    pair: ChatPair,
) -> int:
    for msg in reversed(msgs):
        fp, text = store.fingerprint(msg)
        if TELEGRAM_PREFIX in text:
            continue
        if store.has(fp):   
            continue

        try:
            logger.info(f" process fingerprint --> {fp} text --> {text[:30]}")
            message_text = msg.get("text") or msg.get("caption") or ""
            message_text = strip_trailing_time(message_text)
            await _send_to_telegram(msg, message_text, maxc, pair)
        except Exception as e:
            logger.error(f"[{pair.name}] Ошибка при отправке сообщения: {e}")
        finally:
            store.add(fp)
            seen_count += 1
    return seen_count
