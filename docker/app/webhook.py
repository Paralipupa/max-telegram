from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import asyncio, os, requests
from browser import BrowserManager
from max_client import MaxClient
from loguru import logger
from fastapi.responses import JSONResponse
from fastapi import status
import tempfile
from constants import WEBHOOK_PATH, MAX_CHAT_ID, TELEGRAM_BOT_TOKEN
from helpers import strip_trailing_time

app = FastAPI()


def _log_background_task(task: asyncio.Task) -> None:
    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is not None:
        logger.error("Background process failed: {!r}", exc)


@app.post(WEBHOOK_PATH, response_class=PlainTextResponse)
async def hook(request: Request) -> str:
    try:
        payload = await request.json()
        t = asyncio.create_task(process(payload))
        t.add_done_callback(_log_background_task)
        return "ok"
    except Exception as e:
        logger.error(f"Error processing payload: {e}")
        return PlainTextResponse("error", status_code=500)


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def catch_all(path: str):
    logger.info(f"Запрошенный путь /{path} не существует")
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "status": "error",
            "details": f"Запрошенный путь /{path} не существует",
        },
    )


async def process(data):
    b = await BrowserManager.get()
    page = b["page"]
    maxc = MaxClient(page)
    chat_id = MAX_CHAT_ID

    await maxc.open_chat(chat_id)

    message = data.get("message") or {}
    from_name = (
        message.get("from", {}).get("first_name")
        if not message.get("from", {}).get("is_bot")
        else None
    )
    text = message.get("text") or message.get("caption") or ""
    text = strip_trailing_time(text)
    # if from_name:
    #     text = f"{from_name}: {text}"
    file_id, media_type = _extract_file_info(message)
    if not text and not file_id:
        raise ValueError("bad request")

    if text or file_id:
        await send_to_max(b, text=text, file_id=file_id, media_type=media_type)


def _extract_file_info(message: dict) -> tuple[str | None, str | None]:
    """Возвращает (file_id, media_type) где media_type: 'photo', 'video', 'file' или None."""
    photos = message.get("photo") or []
    if photos:
        return photos[-1].get("file_id"), "photo"

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
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getFile",
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
        f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}",
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
