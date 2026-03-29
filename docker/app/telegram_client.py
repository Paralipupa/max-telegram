import requests
from constants import (
    TOKEN,
    TELEGRAM_CHAT_ID,
    TELEGRAM_SEND_MESSAGE_URL,
    TELEGRAM_SEND_PHOTO_URL,
    TELEGRAM_SEND_MEDIA_GROUP_URL,
    TELEGRAM_SEND_DOCUMENT_URL,
    TELEGRAM_SEND_VIDEO_URL,
)
from loguru import logger

def send(text):
    """Отправляет текстовое сообщение в Telegram."""
    logger.info(f"Отправляем сообщение: {text}")
    requests.post(
        TELEGRAM_SEND_MESSAGE_URL.format(token=TOKEN),
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
    )
    logger.info(f"Отправлено сообщение: {text}")

def send_photo(photo_url, caption=None):
    """Отправляет фото в Telegram по URL (прямая ссылка)."""
    logger.info(f"Отправляем фото: {caption}")
    data = {"chat_id": TELEGRAM_CHAT_ID, "photo": photo_url}
    if caption:
        data["caption"] = caption
    requests.post(TELEGRAM_SEND_PHOTO_URL.format(token=TOKEN), json=data)
    logger.info(f"Отправлено фото: {caption}")


def send_document(
    document: str | bytes, caption: str | None = None, filename: str = "file"
) -> None:
    """Отправляет файл в Telegram: по URL или как bytes (multipart)."""
    logger.info(f"Отправляем документ: {caption} filename: {filename}")
    if isinstance(document, bytes):
        data: dict = {"chat_id": TELEGRAM_CHAT_ID}
        if caption:
            data["caption"] = caption
        requests.post(
            TELEGRAM_SEND_DOCUMENT_URL.format(token=TOKEN),
            data=data,
            files={"document": (filename, document)},
        )
    else:
        data = {"chat_id": TELEGRAM_CHAT_ID, "document": document}
        if caption:
            data["caption"] = caption
        requests.post(TELEGRAM_SEND_DOCUMENT_URL.format(token=TOKEN), json=data)
    logger.info(f"Отправлен документ: {caption}")

def send_video(
    video: str | bytes, caption: str | None = None, filename: str = "video.mp4"
) -> None:
    """Отправляет видео в Telegram: по URL или как bytes (multipart)."""
    logger.info(f"Отправляем видео: {caption} filename: {filename}")
    if isinstance(video, bytes):
        data: dict = {"chat_id": TELEGRAM_CHAT_ID}
        if caption:
            data["caption"] = caption
        requests.post(
            TELEGRAM_SEND_VIDEO_URL.format(token=TOKEN),
            data=data,
            files={"video": (filename, video)},
        )
    else:
        data = {"chat_id": TELEGRAM_CHAT_ID, "video": video}
        if caption:
            data["caption"] = caption
        requests.post(TELEGRAM_SEND_VIDEO_URL.format(token=TOKEN), json=data)
    logger.info(f"Отправлено видео: {caption}")

def send_media_group(photo_urls: list[str], caption: str | None = None) -> None:
    """Отправляет несколько фото одним альбомом (sendMediaGroup)."""
    logger.info(f"Отправляем альбом: {caption}")
    urls = [u for u in photo_urls if isinstance(u, str) and u.strip()]
    if not urls:
        return
    media = []
    for i, url in enumerate(urls):
        item = {"type": "photo", "media": url}
        if i == 0 and caption:
            item["caption"] = caption
        media.append(item)
    requests.post(
        TELEGRAM_SEND_MEDIA_GROUP_URL.format(token=TOKEN),
        json={"chat_id": TELEGRAM_CHAT_ID, "media": media},
    )
    logger.info(f"Отправлен альбом: {caption}")