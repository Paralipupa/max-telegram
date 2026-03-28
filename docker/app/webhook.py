from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi import status
import asyncio
from loguru import logger
from constants import WEBHOOK_PATH
from processing import process, log_background_task

app = FastAPI()

logger.info(f"WEBHOOK_PATH: {WEBHOOK_PATH}")

@app.post(WEBHOOK_PATH, response_class=PlainTextResponse)
async def hook(request: Request) -> str:
    try:
        payload = await request.json()
        t = asyncio.create_task(process(payload))
        t.add_done_callback(log_background_task)
        return "ok"
    except Exception as e:
        logger.error(f"Error processing payload: {e}")
        return PlainTextResponse("error", status_code=500)


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def catch_all(request: Request, path: str):
    logger.info(
        f"Запрошенный путь /{path} не существует. "
        f"host: {request.headers.get('host')} "
        f"user-agent: {request.headers.get('user-agent')} "
        f"x-forwarded-for: {request.headers.get('x-forwarded-for')} "
        f"x-forwarded-host: {request.headers.get('x-forwarded-host')} "
        f"x-forwarded-proto: {request.headers.get('x-forwarded-proto')} "
        f"x-forwarded-port: {request.headers.get('x-forwarded-port')} "
        f"x-forwarded-server: {request.headers.get('x-forwarded-server')} "
        f"x-forwarded-client-ip: {request.headers.get('x-forwarded-client-ip')} "
        f"x-forwarded-client-port: {request.headers.get('x-forwarded-client-port')} "
    )
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "status": "error",
            "details": "Запрошенный путь не существует",
            "path": path,
        },
    )
