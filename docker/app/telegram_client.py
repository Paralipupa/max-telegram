import requests
import os

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MAX_CHAT_ID = os.getenv("MAX_CHAT_ID")
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}"
TELEGRAM_SEND_MESSAGE_URL = f"{TELEGRAM_API_URL}/sendMessage"
TELEGRAM_SEND_PHOTO_URL = f"{TELEGRAM_API_URL}/sendPhoto"
TELEGRAM_SEND_MEDIA_GROUP_URL = f"{TELEGRAM_API_URL}/sendMediaGroup"
TELEGRAM_SEND_DOCUMENT_URL = f"{TELEGRAM_API_URL}/sendDocument"
TELEGRAM_SEND_VIDEO_URL = f"{TELEGRAM_API_URL}/sendVideo"


def send(text):
    """Отправляет текстовое сообщение в Telegram."""
    requests.post(
        TELEGRAM_SEND_MESSAGE_URL.format(token=TOKEN),
        json={"chat_id": CHAT_ID, "text": text},
    )


def send_photo(photo_url, caption=None):
    """Отправляет фото в Telegram по URL (прямая ссылка)."""
    data = {"chat_id": CHAT_ID, "photo": photo_url}
    if caption:
        data["caption"] = caption
    requests.post(TELEGRAM_SEND_PHOTO_URL.format(token=TOKEN), json=data)


def send_document(document: str | bytes, caption: str | None = None, filename: str = "file") -> None:
    """Отправляет файл в Telegram: по URL или как bytes (multipart)."""
    if isinstance(document, bytes):
        data: dict = {"chat_id": CHAT_ID}
        if caption:
            data["caption"] = caption
        requests.post(
            TELEGRAM_SEND_DOCUMENT_URL.format(token=TOKEN),
            data=data,
            files={"document": (filename, document)},
        )
    else:
        data = {"chat_id": CHAT_ID, "document": document}
        if caption:
            data["caption"] = caption
        requests.post(TELEGRAM_SEND_DOCUMENT_URL.format(token=TOKEN), json=data)


def send_video(video: str | bytes, caption: str | None = None, filename: str = "video.mp4") -> None:
    """Отправляет видео в Telegram: по URL или как bytes (multipart)."""
    if isinstance(video, bytes):
        data: dict = {"chat_id": CHAT_ID}
        if caption:
            data["caption"] = caption
        requests.post(
            TELEGRAM_SEND_VIDEO_URL.format(token=TOKEN),
            data=data,
            files={"video": (filename, video)},
        )
    else:
        data = {"chat_id": CHAT_ID, "video": video}
        if caption:
            data["caption"] = caption
        requests.post(TELEGRAM_SEND_VIDEO_URL.format(token=TOKEN), json=data)


def send_media_group(photo_urls: list[str], caption: str | None = None) -> None:
    """Отправляет несколько фото одним альбомом (sendMediaGroup)."""
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
        json={"chat_id": CHAT_ID, "media": media},
    )
