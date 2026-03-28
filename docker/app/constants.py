import os
import re
from dataclasses import dataclass

DEDUP_PATH = "/data/dedup.sqlite3"
MEDIA_GROUP_TIMEOUT = 2.0  # секунды ожидания хвостовых фото
TAIL_LIMIT = int(os.getenv("TAIL_LIMIT", "30"))
HEADLESS = os.getenv("HEADLESS", "true") == "true"

MAX_PREFIX = "⟨M⟩"
TELEGRAM_PREFIX = "⟨T⟩"


@dataclass
class ChatPair:
    """Конфигурация одной пары чатов Telegram ↔ Max."""
    name: str
    max_chat_id: str
    telegram_bot_token: str
    telegram_chat_id: str

    @property
    def max_url(self) -> str:
        return f"https://web.max.ru/{self.max_chat_id}"

    @property
    def tg_api(self) -> str:
        return f"https://api.telegram.org/bot{self.telegram_bot_token}"

    @property
    def tg_file_api(self) -> str:
        return f"https://api.telegram.org/file/bot{self.telegram_bot_token}"

    @property
    def webhook_path(self) -> str:
        return f"/bot{self.telegram_bot_token}/"

    @property
    def dedup_path(self) -> str:
        slug = re.sub(r"[^\w-]", "_", self.name)
        return f"/data/dedup_{slug}.sqlite3"


def load_pairs() -> list[ChatPair]:
    """
    Загружает пары чатов из переменных среды.

    Новый формат (несколько пар):
        PAIR_1_NAME=семья
        PAIR_1_MAX_CHAT_ID=...
        PAIR_1_TELEGRAM_BOT_TOKEN=...
        PAIR_1_TELEGRAM_CHAT_ID=...

        PAIR_2_NAME=работа
        PAIR_2_MAX_CHAT_ID=...
        ...

    Старый формат (обратная совместимость, одна пара):
        MAX_CHAT_ID=...
        TELEGRAM_BOT_TOKEN=...
        TELEGRAM_CHAT_ID=...
    """
    pairs = []
    n = 1
    while True:
        prefix = f"PAIR_{n}_"
        max_chat_id = os.getenv(f"{prefix}MAX_CHAT_ID")
        token = os.getenv(f"{prefix}TELEGRAM_BOT_TOKEN")
        tg_chat_id = os.getenv(f"{prefix}TELEGRAM_CHAT_ID")
        if not (max_chat_id and token and tg_chat_id):
            break
        name = os.getenv(f"{prefix}NAME") or f"pair-{n}"
        pairs.append(ChatPair(
            name=name,
            max_chat_id=max_chat_id,
            telegram_bot_token=token,
            telegram_chat_id=tg_chat_id,
        ))
        n += 1

    # Обратная совместимость: старые переменные без номера
    if not pairs:
        max_chat_id = os.getenv("MAX_CHAT_ID")
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        tg_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if max_chat_id and token and tg_chat_id:
            pairs.append(ChatPair(
                name="default",
                max_chat_id=max_chat_id,
                telegram_bot_token=token,
                telegram_chat_id=tg_chat_id,
            ))

    return pairs
