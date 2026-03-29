import asyncio
import os
import uvicorn
from bridge import run_bridge
from webhook import create_app
from browser import BrowserManager
from loguru import logger
from constants import load_pairs, DEDUP_RESET


async def main():
    pairs = load_pairs()
    if not pairs:
        logger.error(
            "Нет пар чатов! Задайте PAIR_1_MAX_CHAT_ID / PAIR_1_TELEGRAM_BOT_TOKEN / "
            "PAIR_1_TELEGRAM_CHAT_ID (или устаревшие MAX_CHAT_ID / TELEGRAM_BOT_TOKEN / "
            "TELEGRAM_CHAT_ID для одной пары)."
        )
        return

    logger.info(f"Загружено {len(pairs)} пар чатов: {[p.name for p in pairs]}")

    # Сбрасываем дедупликацию и заранее открываем страницы для каждой пары.
    # Последовательная инициализация гарантирует создание браузера до старта фоновых задач.
    for pair in pairs:
        if os.path.exists(pair.dedup_path) and DEDUP_RESET:
            logger.info(f"[{pair.name}] Сбрасываем дедупликацию: {pair.dedup_path}")
            try:
                os.remove(pair.dedup_path)
            except Exception as e:
                logger.error(f"[{pair.name}] Ошибка сброса дедупликации: {e}")
        await BrowserManager.get(pair.name, pair.max_url)

    app = create_app(pairs)
    config = uvicorn.Config(app, host="0.0.0.0", port=8081, log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        *[run_bridge(pair, len(pairs)) for pair in pairs],
        server.serve(),
    )


if __name__ == "__main__":
    asyncio.run(main())
