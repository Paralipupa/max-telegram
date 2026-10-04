import requests
from constants import ChatPair, TELEGRAM_PREFIX
from loguru import logger


class TelegramUnauthorizedError(RuntimeError):
    """Telegram отклонил токен бота; до перезапуска конфигурация не изменится."""


def _post_telegram(pair: ChatPair, method: str, **kwargs):
    try:
        response = requests.post(f"{pair.tg_api}/{method}", timeout=30, **kwargs)
        result = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise RuntimeError(f"[{pair.name}] Telegram {method}: ошибка запроса ({type(exc).__name__})") from None
    if response.status_code == 401:
        raise TelegramUnauthorizedError(
            f"[{pair.name}] Telegram отклонил токен бота (HTTP 401). "
            "Проверьте TELEGRAM_BOT_TOKEN в .env и пересоздайте контейнер"
        )
    if not isinstance(result, dict) or response.status_code != 200 or not result.get("ok"):
        description = result.get("description", "неизвестная ошибка") if isinstance(result, dict) else "некорректный ответ"
        raise RuntimeError(
            f"[{pair.name}] Telegram {method}: HTTP {response.status_code}, {description}"
        )
    return result.get("result")


def send(pair: ChatPair, text: str) -> None:
    """Отправляет текстовое сообщение в Telegram."""
    logger.info(f"[{pair.name}] Отправляем текст: {text[:20]}...")
    _post_telegram(pair, "sendMessage", json={"chat_id": pair.telegram_chat_id, "text": text})
    logger.info(f"[{pair.name}] Текст отправлен")


def send_photo(pair: ChatPair, photo_url: str, caption: str | None = None) -> None:
    """Отправляет фото в Telegram по URL."""
    logger.info(f"[{pair.name}] Отправляем фото: {(caption or '')[:20]}...")
    data: dict = {"chat_id": pair.telegram_chat_id, "photo": photo_url}
    if caption:
        prefix, text = caption.split(TELEGRAM_PREFIX)
        if text.strip().startswith(prefix):
            caption = prefix + TELEGRAM_PREFIX + text.strip()[len(prefix):]
        data["caption"] = caption
    _post_telegram(pair, "sendPhoto", json=data)
    logger.info(f"[{pair.name}] Фото отправлено")


def send_document(
    pair: ChatPair,
    document: str | bytes,
    caption: str | None = None,
    filename: str = "file",
) -> None:
    """Отправляет файл в Telegram: по URL или как bytes (multipart)."""
    logger.info(f"[{pair.name}] Отправляем документ: {(caption or '')[:20]}... filename={filename}")
    if isinstance(document, bytes):
        data: dict = {"chat_id": pair.telegram_chat_id}
        if caption:
            data["caption"] = caption
        _post_telegram(pair, "sendDocument", data=data, files={"document": (filename, document)})
    else:
        data = {"chat_id": pair.telegram_chat_id, "document": document}
        if caption:
            data["caption"] = caption
        _post_telegram(pair, "sendDocument", json=data)
    logger.info(f"[{pair.name}] Документ отправлен")


def send_video(
    pair: ChatPair,
    video: str | bytes,
    caption: str | None = None,
    filename: str = "video.mp4",
) -> None:
    """Отправляет видео в Telegram: по URL или как bytes (multipart)."""
    logger.info(f"[{pair.name}] Отправляем видео: {(caption or '')[:20]}... filename={filename}")
    if isinstance(video, bytes):
        data: dict = {"chat_id": pair.telegram_chat_id}
        if caption:
            data["caption"] = caption
        _post_telegram(pair, "sendVideo", data=data, files={"video": (filename, video)})
    else:
        data = {"chat_id": pair.telegram_chat_id, "video": video}
        if caption:
            data["caption"] = caption
        _post_telegram(pair, "sendVideo", json=data)
    logger.info(f"[{pair.name}] Видео отправлено")


def send_media_group(pair: ChatPair, photo_urls: list[str], caption: str | None = None) -> None:
    """Отправляет несколько фото одним альбомом (sendMediaGroup)."""
    logger.info(f"[{pair.name}] Отправляем альбом: {len(photo_urls)} фото - {(caption or '')[:20]}...")
    urls = [u for u in photo_urls if isinstance(u, str) and u.strip()]
    if not urls:
        return
    media = []
    for i, url in enumerate(urls):
        item: dict = {"type": "photo", "media": url}
        if i == 0 and caption:
            item["caption"] = caption
        media.append(item)
    _post_telegram(pair, "sendMediaGroup", json={"chat_id": pair.telegram_chat_id, "media": media})
    logger.info(f"[{pair.name}] Альбом отправлен")
