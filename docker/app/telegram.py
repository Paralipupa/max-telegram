import requests
from constants import TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_API_URL

def send_telegram(text):
    requests.post(
        f"{TELEGRAM_API_URL}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text}
    )
