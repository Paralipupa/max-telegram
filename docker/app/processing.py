import asyncio, os, tempfile, requests
from browser import BrowserManager
from max_client import MaxClient
from loguru import logger
from constants import ChatPair, MEDIA_GROUP_TIMEOUT
from helpers import strip_trailing_time, apply_text_links
from collage import make_collage

# Буфер медиагрупп: (pair_name, group_id) → список сообщений.
# Ключ включает имя пары, чтобы разные пары с одинаковыми group_id не конфликтовали.
_media_group_buffer: dict[tuple[str, str], list[dict]] = {}


def log_background_task(task: asyncio.Task) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.error("Background process failed: {!r}", exc)


async def process(data: dict, pair: ChatPair) -> None:
    message = data.get("message") or {}
    media_group_id = message.get("media_group_id")

    if media_group_id:
        key = (pair.name, media_group_id)
        is_first = key not in _media_group_buffer
        _media_group_buffer.setdefault(key, []).append(message)
        if is_first:
            t = asyncio.create_task(_delayed_send_media_group(key, pair))
            t.add_done_callback(log_background_task)
        return

    await _process_single_message(message, pair)


async def _delayed_send_media_group(key: tuple[str, str], pair: ChatPair) -> None:
    """Ждёт MEDIA_GROUP_TIMEOUT секунд, затем отправляет коллаж из всех фото группы."""
    await asyncio.sleep(MEDIA_GROUP_TIMEOUT)
    messages = _media_group_buffer.pop(key, [])
    if not messages:
        return

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

    logger.info(f"[{pair.name}] Медиагруппа {key[1]}: скачиваем {len(photo_ids)} фото для коллажа")

    local_paths: list[str] = []
    collage_path: str | None = None
    try:
        for fid in photo_ids:
            local_paths.append(_download_telegram_file(fid, pair))

        collage_bytes = make_collage(local_paths)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        tmp.write(collage_bytes)
        tmp.close()
        collage_path = tmp.name

        b = await BrowserManager.get(pair.name, pair.max_url)
        async with b["lock"]:
            maxc = MaxClient(b["page"])
            await maxc.open_chat(pair.max_chat_id)
            await maxc.send_photo(collage_path, caption=caption or "")
    finally:
        for p in local_paths:
            if os.path.exists(p):
                os.remove(p)
        if collage_path and os.path.exists(collage_path):
            os.remove(collage_path)


async def _process_single_message(message: dict, pair: ChatPair) -> None:
    """Обрабатывает одиночное (не медиагрупповое) сообщение."""
    text = message.get("text") or message.get("caption") or ""
    entities = message.get("entities") or message.get("caption_entities") or []
    text = strip_trailing_time(apply_text_links(text, entities))
    file_id, media_type = _extract_file_info(message)
    if not text and not file_id:
        raise ValueError("bad request")

    b = await BrowserManager.get(pair.name, pair.max_url)
    async with b["lock"]:
        maxc = MaxClient(b["page"])
        await maxc.open_chat(pair.max_chat_id)
        await send_to_max(b, text=text, file_id=file_id, media_type=media_type, pair=pair)


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


def _download_telegram_file(file_id: str, pair: ChatPair) -> str:
    file_resp = requests.get(
        f"{pair.tg_api}/getFile",
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
        f"{pair.tg_file_api}/{file_path}",
        timeout=30,
    )
    download_resp.raise_for_status()
    with open(out_path, "wb") as f:
        f.write(download_resp.content)

    return out_path


async def send_to_max(
    b: dict, text: str, file_id: str | None = None, media_type: str | None = None, pair: ChatPair = None
) -> None:
    local_path = None
    maxc = MaxClient(b["page"])
    try:
        if file_id:
            local_path = _download_telegram_file(file_id, pair)
            logger.info(
                f"[{pair.name}] Скачан {media_type}: {local_path}, размер: {os.path.getsize(local_path)}"
            )
            if media_type in ("photo", "video"):
                await maxc.send_photo(local_path, caption=text or "")
            else:
                await maxc.send_file(local_path, caption=text or "")
        elif text:
            await maxc.send_message(text)
    except Exception as e:
        try:
            logger.error(f"[{pair.name}] send_to_max failed: {e} url={b['page'].url!r}")
        except Exception:
            logger.error(f"[{pair.name}] send_to_max failed: {e}")
        raise
    finally:
        if local_path and os.path.exists(local_path):
            os.remove(local_path)
