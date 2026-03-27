import os
import threading
import time

import requests
from loguru import logger

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
MAX_CHAT_ID = os.getenv("MAX_CHAT_ID")
TELEGRAM_API_URL = "https://api.telegram.org/bot{token}"
TELEGRAM_SEND_MESSAGE_URL = f"{TELEGRAM_API_URL}/sendMessage"
TELEGRAM_SEND_PHOTO_URL = f"{TELEGRAM_API_URL}/sendPhoto"
TELEGRAM_SEND_MEDIA_GROUP_URL = f"{TELEGRAM_API_URL}/sendMediaGroup"
TELEGRAM_SEND_DOCUMENT_URL = f"{TELEGRAM_API_URL}/sendDocument"
TELEGRAM_SEND_VIDEO_URL = f"{TELEGRAM_API_URL}/sendVideo"

# Same-process guard: duplicate send() with the same dedup_key (e.g. fingerprint) within window.
_tg_send_lock = threading.Lock()
_recent_text_sends: dict[str, float] = {}
_DEDUP_WINDOW_SEC = 30.0


def send(text: str, *, dedup_key: str | None = None) -> None:
    """Отправляет текстовое сообщение в Telegram."""
    key = dedup_key if dedup_key else text
    now = time.monotonic()
    with _tg_send_lock:
        prev = _recent_text_sends.get(key)
        if prev is not None and (now - prev) < _DEDUP_WINDOW_SEC:
            logger.warning(
                "telegram send skipped (duplicate within {:.0f}s): key={!r}",
                _DEDUP_WINDOW_SEC,
                key[:64] + ("…" if len(key) > 64 else ""),
            )
            return
        _recent_text_sends[key] = now
        if len(_recent_text_sends) > 5000:
            cutoff = now - 120.0
            for k, t in list(_recent_text_sends.items()):
                if t < cutoff:
                    del _recent_text_sends[k]

    url = TELEGRAM_SEND_MESSAGE_URL.format(token=TOKEN)
    r = requests.post(
        url,
        json={"chat_id": CHAT_ID, "text": text},
        timeout=60,
    )
    logger.info(f"telegram sendMessage: {r.text} - {dedup_key}")
    try:
        data = r.json()
    except Exception:
        data = {}
    mid = None
    if isinstance(data.get("result"), dict):
        mid = data["result"].get("message_id")
    if r.ok and data.get("ok"):
        logger.info(
            "telegram sendMessage ok message_id={} chat_id={} pid={}",
            mid,
            CHAT_ID,
            os.getpid(),
        )
    else:
        logger.error(
            "telegram sendMessage failed status={} body={!r}",
            r.status_code,
            r.text[:500],
        )


def send_photo(photo_url, caption=None):
    """Отправляет фото в Telegram по URL (прямая ссылка)."""
    data = {"chat_id": CHAT_ID, "photo": photo_url}
    if caption:
        data["caption"] = caption
    requests.post(TELEGRAM_SEND_PHOTO_URL.format(token=TOKEN), json=data)


def send_document(document_url: str, caption: str | None = None) -> None:
    """Отправляет файл в Telegram по URL (прямая ссылка)."""
    data: dict = {"chat_id": CHAT_ID, "document": document_url}
    if caption:
        data["caption"] = caption
    requests.post(TELEGRAM_SEND_DOCUMENT_URL.format(token=TOKEN), json=data)


def send_video(video_url: str, caption: str | None = None) -> None:
    """Отправляет видео в Telegram по URL."""
    data: dict = {"chat_id": CHAT_ID, "video": video_url}
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
