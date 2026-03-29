import requests
from constants import ChatPair
from loguru import logger


def send(pair: ChatPair, text: str) -> None:
    """Отправляет текстовое сообщение в Telegram."""
    logger.info(f"[{pair.name}] Отправляем текст: {text}")
    requests.post(f"{pair.tg_api}/sendMessage", json={"chat_id": pair.telegram_chat_id, "text": text})
    logger.info(f"[{pair.name}] Текст отправлен")


def send_photo(pair: ChatPair, photo_url: str, caption: str | None = None) -> None:
    """Отправляет фото в Telegram по URL."""
    logger.info(f"[{pair.name}] Отправляем фото: {caption}")
    data: dict = {"chat_id": pair.telegram_chat_id, "photo": photo_url}
    if caption:
        data["caption"] = caption
    requests.post(f"{pair.tg_api}/sendPhoto", json=data)
    logger.info(f"[{pair.name}] Фото отправлено")


def send_document(
    pair: ChatPair,
    document: str | bytes,
    caption: str | None = None,
    filename: str = "file",
) -> None:
    """Отправляет файл в Telegram: по URL или как bytes (multipart)."""
    logger.info(f"[{pair.name}] Отправляем документ: {caption} filename={filename}")
    if isinstance(document, bytes):
        data: dict = {"chat_id": pair.telegram_chat_id}
        if caption:
            data["caption"] = caption
        requests.post(f"{pair.tg_api}/sendDocument", data=data, files={"document": (filename, document)})
    else:
        data = {"chat_id": pair.telegram_chat_id, "document": document}
        if caption:
            data["caption"] = caption
        requests.post(f"{pair.tg_api}/sendDocument", json=data)
    logger.info(f"[{pair.name}] Документ отправлен")


def send_video(
    pair: ChatPair,
    video: str | bytes,
    caption: str | None = None,
    filename: str = "video.mp4",
) -> None:
    """Отправляет видео в Telegram: по URL или как bytes (multipart)."""
    logger.info(f"[{pair.name}] Отправляем видео: {caption} filename={filename}")
    if isinstance(video, bytes):
        data: dict = {"chat_id": pair.telegram_chat_id}
        if caption:
            data["caption"] = caption
        requests.post(f"{pair.tg_api}/sendVideo", data=data, files={"video": (filename, video)})
    else:
        data = {"chat_id": pair.telegram_chat_id, "video": video}
        if caption:
            data["caption"] = caption
        requests.post(f"{pair.tg_api}/sendVideo", json=data)
    logger.info(f"[{pair.name}] Видео отправлено")


def send_media_group(pair: ChatPair, photo_urls: list[str], caption: str | None = None) -> None:
    """Отправляет несколько фото одним альбомом (sendMediaGroup)."""
    logger.info(f"[{pair.name}] Отправляем альбом: {len(photo_urls)} фото - {caption}")
    urls = [u for u in photo_urls if isinstance(u, str) and u.strip()]
    if not urls:
        return
    media = []
    for i, url in enumerate(urls):
        item: dict = {"type": "photo", "media": url}
        if i == 0 and caption:
            item["caption"] = caption
        media.append(item)
    requests.post(
        f"{pair.tg_api}/sendMediaGroup",
        json={"chat_id": pair.telegram_chat_id, "media": media},
    )
    logger.info(f"[{pair.name}] Альбом отправлен")
