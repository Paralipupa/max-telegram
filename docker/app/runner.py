
import asyncio
import os
import uvicorn
from bridge import run_bridge
from webhook import app
from browser import BrowserManager
from loguru import logger
from constants import DEDUP_PATH, DEDUP_RESET

async def main():
    if os.path.exists(DEDUP_PATH) and DEDUP_RESET:
        logger.info(f"Сбрасываем дедупликацию: {DEDUP_PATH}")
        try:
            os.remove(DEDUP_PATH)
        except Exception as e:
            logger.error(f"Ошибка при сбросе дедупликации: {e}")

    await BrowserManager.get()

    config = uvicorn.Config(app, host="0.0.0.0", port=8081, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        run_bridge(),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
