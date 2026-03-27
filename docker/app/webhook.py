from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
import asyncio, os, requests
from browser import BrowserManager
from max_client import MaxClient
from loguru import logger
from fastapi.responses import JSONResponse
from fastapi import status
import tempfile
import re

MAX_CHAT_ID = os.getenv("MAX_CHAT_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_PATH = f"/bot{TELEGRAM_BOT_TOKEN}/"

app = FastAPI()


@app.post(WEBHOOK_PATH, response_class=PlainTextResponse)
async def hook(request: Request) -> str:
    try:
        payload = await request.json()
        asyncio.create_task(process(payload))
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
    text = message.get("text") or message.get("caption") or ""
    if re.search(r'\d{2}:\d{2}$', text):
        text = re.sub(r'\s*\d{2}:\d{2}$', '', text)
    photo_file_id = _extract_photo_file_id(message)
    if not text and not photo_file_id:
        raise ValueError("bad request")

    await send_to_max(b, text=text, photo_file_id=photo_file_id)


def _extract_photo_file_id(message: dict) -> str | None:
    photos = message.get("photo") or []
    if photos:
        largest = photos[-1]
        return largest.get("file_id")

    document = message.get("document") or {}
    mime_type = (document.get("mime_type") or "").lower()
    if mime_type.startswith("image/"):
        return document.get("file_id")

    return None


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


async def send_to_max(b, text: str, photo_file_id: str | None = None) -> None:
    local_photo_path = None
    page = b["page"]
    maxc = MaxClient(page)
    try:
        if photo_file_id:
            local_photo_path = _download_telegram_file(photo_file_id)
            logger.info(
                f"Downloaded photo to {local_photo_path}, size: {os.path.getsize(local_photo_path)}"
            )
            await maxc.send_photo(local_photo_path, caption=text or "")
        elif text:
            await maxc.send_message(text)
    except Exception as e:
        try:
            logger.error(f"send_to_max failed: {e} url={page.url!r}")
        except Exception:
            logger.error(f"send_to_max failed: {e}")
        raise
    finally:
        if local_photo_path and os.path.exists(local_photo_path):
            os.remove(local_photo_path)
