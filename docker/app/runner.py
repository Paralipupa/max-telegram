
import asyncio
import os
import uvicorn
from bridge import run_bridge
from webhook import app
from browser import BrowserManager

_DEDUP_PATH = "/data/dedup.sqlite3"


async def main():
    # Сбрасываем дедупликацию при каждом запуске контейнера
    if os.path.exists(_DEDUP_PATH):
        os.remove(_DEDUP_PATH)

    await BrowserManager.get()

    config = uvicorn.Config(app, host="0.0.0.0", port=8081, log_level="info")
    server = uvicorn.Server(config)

    # Оба компонента в одном event loop — asyncio.Lock в BrowserManager работает корректно
    await asyncio.gather(
        run_bridge(),
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
