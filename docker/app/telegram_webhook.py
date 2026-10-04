"""Проверка и настройка webhook для ботов из текущего .env."""

import os
from urllib.parse import urlsplit

from loguru import logger

from constants import ChatPair, load_pairs
from telegram_client import _post_telegram


def webhook_base_url() -> str:
    value = os.getenv("TELEGRAM_WEBHOOK_BASE_URL") or os.getenv("VIRTUAL_HOST", "")
    value = value.strip().split(",", 1)[0]
    if "://" not in value:
        value = f"https://{value}"
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in ("", "/"):
        raise ValueError("Задайте HTTPS-адрес в TELEGRAM_WEBHOOK_BASE_URL или VIRTUAL_HOST")
    return value.rstrip("/")


def ensure_webhook(pair: ChatPair, base_url: str) -> bool:
    expected = f"{base_url}{pair.webhook_path}"
    info = _post_telegram(pair, "getWebhookInfo")
    current = info.get("url", "")
    if current == expected:
        logger.info(f"[{pair.name}] Webhook Telegram уже настроен")
        return False
    if current and urlsplit(current).hostname != urlsplit(base_url).hostname:
        raise RuntimeError(
            f"[{pair.name}] Webhook Telegram указывает на другой хост; "
            "автоматическая замена пропущена"
        )
    _post_telegram(pair, "setWebhook", json={"url": expected})
    logger.info(f"[{pair.name}] Webhook Telegram настроен")
    return True


def main() -> None:
    base_url = webhook_base_url()
    failed = False
    for pair in load_pairs():
        try:
            ensure_webhook(pair, base_url)
        except Exception as exc:
            logger.error(f"[{pair.name}] Не удалось настроить webhook: {exc}")
            failed = True
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
