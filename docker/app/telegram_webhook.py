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
    pending = info.get("pending_update_count", 0)
    last_error = (info.get("last_error_message") or "").replace(
        pair.telegram_bot_token, "[скрыто]"
    )
    if pending or last_error:
        logger.warning(
            f"[{pair.name}] Telegram webhook: ожидают доставки {pending}, "
            f"последняя ошибка: {last_error or 'нет'}"
        )
    allowed_updates = info.get("allowed_updates") or []
    if current == expected:
        if allowed_updates and "message" not in allowed_updates:
            _post_telegram(
                pair, "setWebhook",
                json={"url": expected, "allowed_updates": [*allowed_updates, "message"]},
            )
            logger.info(f"[{pair.name}] Webhook Telegram: включена доставка сообщений")
            return True
        logger.info(f"[{pair.name}] Webhook Telegram уже настроен")
        return False
    if current and urlsplit(current).hostname != urlsplit(base_url).hostname:
        raise RuntimeError(
            f"[{pair.name}] Webhook Telegram указывает на другой хост; "
            "автоматическая замена пропущена"
        )
    # Telegram сохраняет allowed_updates от прежней настройки, если их не указать.
    updates = [*allowed_updates, "message"] if allowed_updates else []
    _post_telegram(pair, "setWebhook", json={"url": expected, "allowed_updates": updates})
    logger.info(f"[{pair.name}] Webhook Telegram настроен")
    return True


def check_bot_visibility(pair: ChatPair) -> None:
    bot = _post_telegram(pair, "getMe")
    chat = _post_telegram(pair, "getChat", json={"chat_id": pair.telegram_chat_id})
    if chat.get("type") not in ("group", "supergroup"):
        return
    if bot.get("can_read_all_group_messages"):
        logger.info(f"[{pair.name}] Бот Telegram может читать сообщения группы")
        return
    member = _post_telegram(
        pair,
        "getChatMember",
        json={"chat_id": pair.telegram_chat_id, "user_id": bot["id"]},
    )
    if member.get("status") not in ("administrator", "creator"):
        logger.warning(
            f"[{pair.name}] Бот @{bot.get('username', '?')} не видит обычные сообщения "
            "группы: отключите privacy mode через @BotFather /setprivacy "
            "и добавьте бота в группу заново либо назначьте его администратором"
        )


def configure_pair(pair: ChatPair, base_url: str) -> None:
    ensure_webhook(pair, base_url)
    try:
        check_bot_visibility(pair)
    except Exception as exc:
        logger.warning(f"[{pair.name}] Не удалось проверить privacy mode бота: {exc}")


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
