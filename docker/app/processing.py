import asyncio, os, tempfile, requests
from browser import BrowserManager
from max_client import MaxClient
from loguru import logger
from constants import (
    MAX_CHAT_ID,
    MEDIA_GROUP_TIMEOUT,
    TELEGRAM_API_URL,
    TELEGRAM_FILE_API_URL,
)
from helpers import strip_trailing_time, apply_text_links
from collage import make_collage

# Буфер медиагрупп: group_id → список сообщений.
# После MEDIA_GROUP_TIMEOUT секунд все фото группы отправляются вместе.
_media_group_buffer: dict[str, list[dict]] = {}


def log_background_task(task: asyncio.Task) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.error("Background process failed: {!r}", exc)


async def process(data: dict) -> None:
    message = data.get("message") or {}
    media_group_id = message.get("media_group_id")

    if media_group_id:
        is_first = media_group_id not in _media_group_buffer
        _media_group_buffer.setdefault(media_group_id, []).append(message)
        if is_first:
            t = asyncio.create_task(_delayed_send_media_group(media_group_id))
            t.add_done_callback(log_background_task)
        return

    await _process_single_message(message)


async def _delayed_send_media_group(group_id: str) -> None:
    """Ждёт MEDIA_GROUP_TIMEOUT секунд, затем отправляет коллаж из всех фото группы."""
    await asyncio.sleep(MEDIA_GROUP_TIMEOUT)
    messages = _media_group_buffer.pop(group_id, [])
    if not messages:
        return

    # Caption берём из первого сообщения, которое его содержит
    caption = ""
    for m in messages:
        raw = m.get("caption") or ""
        if raw:
            entities = m.get("caption_entities") or []
            caption = strip_trailing_time(apply_text_links(raw, entities))
            break

    photo_ids = []
    for msg in messages:
        photos = msg.get("photo") or []
        fid = _pick_photo_id(photos, max_width=800)
        if fid:
            photo_ids.append(fid)

    if not photo_ids:
        return

    logger.info(f"Медиагруппа {group_id}: скачиваем {len(photo_ids)} фото для коллажа")

    local_paths: list[str] = []
    collage_path: str | None = None
    try:
        for fid in photo_ids:
            local_paths.append(_download_telegram_file(fid))

        collage_bytes = make_collage(local_paths)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp.write(collage_bytes)
        tmp.close()
        collage_path = tmp.name

        b = await BrowserManager.get()
        page = b["page"]
        maxc = MaxClient(page)

        async with BrowserManager.lock:
            await maxc.open_chat(MAX_CHAT_ID)
            await maxc.send_photo(collage_path, caption=caption or "")
    finally:
        for p in local_paths:
            if os.path.exists(p):
                os.remove(p)
        if collage_path and os.path.exists(collage_path):
            os.remove(collage_path)


async def _process_single_message(message: dict) -> None:
    """Обрабатывает одиночное (не медиагрупповое) сообщение."""
    b = await BrowserManager.get()
    page = b["page"]
    maxc = MaxClient(page)

    text = message.get("text") or message.get("caption") or ""
    entities = message.get("entities") or message.get("caption_entities") or []
    text = strip_trailing_time(apply_text_links(text, entities))
    file_id, media_type = _extract_file_info(message)
    if not text and not file_id:
        raise ValueError("bad request")

    async with BrowserManager.lock:
        await maxc.open_chat(MAX_CHAT_ID)
        await send_to_max(b, text=text, file_id=file_id, media_type=media_type)


def _pick_photo_id(photos: list[dict], max_width: int | None = None) -> str | None:
    """
    Выбирает file_id фото по размеру.
    max_width=None — максимальное разрешение (для одиночного фото).
    max_width=N    — наилучшее качество среди фото шириной ≤ N (для медиагруппы).
    """
    if not photos:
        return None
    if max_width is None:
        best = max(photos, key=lambda p: p.get("width", 0) * p.get("height", 0))
    else:
        candidates = [p for p in photos if p.get("width", 0) <= max_width]
        pool = candidates if candidates else photos
        best = max(pool, key=lambda p: p.get("width", 0) * p.get("height", 0))
    return best.get("file_id")


def _extract_file_info(message: dict) -> tuple[str | None, str | None]:
    """Возвращает (file_id, media_type) где media_type: 'photo', 'video', 'file' или None."""
    photos = message.get("photo") or []
    if photos:
        return _pick_photo_id(photos), "photo"

    video = message.get("video") or {}
    if video.get("file_id"):
        return video["file_id"], "video"

    document = message.get("document") or {}
    file_id = document.get("file_id")
    if file_id:
        mime_type = (document.get("mime_type") or "").lower()
        if mime_type.startswith("image/"):
            return file_id, "photo"
        if mime_type.startswith("video/"):
            return file_id, "video"
        return file_id, "file"

    return None, None


def _download_telegram_file(file_id: str) -> str:
    file_resp = requests.get(
        f"{TELEGRAM_API_URL}/getFile",
        params={"file_id": file_id},
        timeout=15,
    )
    file_resp.raise_for_status()
    file_path = file_resp.json()["result"]["file_path"]
    ext = os.path.splitext(file_path)[1] or ".jpg"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
    tmp.close()
    out_path = tmp.name

    download_resp = requests.get(
        f"{TELEGRAM_FILE_API_URL}/{file_path}",
        timeout=30,
    )
    download_resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(download_resp.content)

    return out_path


async def send_to_max(
    b, text: str, file_id: str | None = None, media_type: str | None = None
) -> None:
    local_path = None
    page = b["page"]
    maxc = MaxClient(page)
    try:
        if file_id:
            local_path = _download_telegram_file(file_id)
            logger.info(
                f"Downloaded {media_type} to {local_path}, size: {os.path.getsize(local_path)}"
            )
            if media_type in ("photo", "video"):
                await maxc.send_photo(local_path, caption=text or "")
            else:
                await maxc.send_file(local_path, caption=text or "")
        elif text:
            await maxc.send_message(text)
    except Exception as e:
        try:
            logger.error(f"send_to_max failed: {e} url={page.url!r}")
        except Exception:
            logger.error(f"send_to_max failed: {e}")
        raise
    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)
