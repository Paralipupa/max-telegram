import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, JSONResponse
from fastapi import status
from loguru import logger
from constants import ChatPair
from processing import process, log_background_task


def create_app(pairs: list[ChatPair]) -> FastAPI:
    """Создаёт FastAPI-приложение с отдельным маршрутом для каждой пары."""
    app = FastAPI()

    for pair in pairs:
        _register_webhook(app, pair)

    # @app.api_route(
    #     "/{path:path}",
    #     methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    # )
    # async def catch_all(request: Request, path: str):
    #     logger.info(
    #         f"Запрошенный путь /{path} не существует. "
    #         f"host: {request.headers.get('host')} "
    #         f"user-agent: {request.headers.get('user-agent')} "
    #         f"x-forwarded-for: {request.headers.get('x-forwarded-for')}"
    #     )
    #     return JSONResponse(
    #         status_code=status.HTTP_404_NOT_FOUND,
    #         content={"status": "error", "details": "Запрошенный путь не существует", "path": path},
    #     )

    return app


def _register_webhook(app: FastAPI, pair: ChatPair) -> None:
    """Регистрирует POST-маршрут для конкретной пары."""
    path = pair.webhook_path
    logger.info(f"[{pair.name}] Регистрируем webhook: {path}")

    async def hook(request: Request) -> str:
        try:
            payload = await request.json()
            t = asyncio.create_task(process(payload, pair))
            t.add_done_callback(log_background_task)
            return "ok"
        except Exception as e:
            logger.error(f"[{pair.name}] Ошибка обработки webhook: {e}")
            return PlainTextResponse("error", status_code=500)

    async def healthcheck(request: Request) -> str:
        return "ok"

    app.add_api_route(path, hook, methods=["POST"], response_class=PlainTextResponse)
    app.add_api_route(path, healthcheck, methods=["GET"], response_class=PlainTextResponse)
