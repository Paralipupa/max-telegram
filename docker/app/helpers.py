import re


def strip_trailing_time(text: str) -> str:
    """Убирает время в конце строки (HH:MM), оставляя символы/эмодзи после него.

    Примеры: "текст 05:56" → "текст", "текст 05:56 ❗️" → "текст ❗️"
    """
    if re.search(r"\d{2}:\d{2}\s*(?:[^\w\s]*)$", text):
        return re.sub(r"\s*\d{2}:\d{2}", "", text)
    return text
