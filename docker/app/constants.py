import os

DEDUP_PATH = "/data/dedup.sqlite3"
DEDUP_RESET = os.getenv("DEDUP_RESET", "false") == "true"
MEDIA_GROUP_TIMEOUT = 2.0  # секунды ожидания хвостовых фото
TAIL_LIMIT = int(os.getenv("TAIL_LIMIT", "30"))
HEADLESS = os.getenv("HEADLESS", "true") == "true"

MAX_PREFIX = "⟨M⟩"
TELEGRAM_PREFIX = "⟨T⟩"

MAX_CHAT_ID = os.getenv("MAX_CHAT_ID")

PAGE_URL = f"https://web.max.ru/{MAX_CHAT_ID}"

TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_PATH = f"/bot{TOKEN}/"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TOKEN}"
TELEGRAM_FILE_API_URL = f"https://api.telegram.org/file/bot{TOKEN}"
TELEGRAM_SEND_MESSAGE_URL = f"{TELEGRAM_API_URL}/sendMessage"
TELEGRAM_SEND_PHOTO_URL = f"{TELEGRAM_API_URL}/sendPhoto"
TELEGRAM_SEND_MEDIA_GROUP_URL = f"{TELEGRAM_API_URL}/sendMediaGroup"
TELEGRAM_SEND_DOCUMENT_URL = f"{TELEGRAM_API_URL}/sendDocument"
TELEGRAM_SEND_VIDEO_URL = f"{TELEGRAM_API_URL}/sendVideo"


