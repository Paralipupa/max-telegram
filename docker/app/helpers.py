import re
import html as _html


def build_html_with_links(text: str, entities: list[dict]) -> str | None:
    """Строит HTML с тегами <a href> для text_link-сущностей.

    Возвращает None, если ссылок нет (нет смысла использовать HTML).
    Переводы строк превращаются в <br>.
    """
    if not text or not entities:
        return None

    links = sorted(
        [e for e in entities if e.get("type") == "text_link" and e.get("url")],
        key=lambda e: e["offset"],
    )
    if not links:
        return None

    def _esc(s: str) -> str:
        return _html.escape(s).replace("\n", "<br>")

    buf = text.encode("utf-16-le")
    result = []
    prev_end = 0

    for entity in links:
        start = entity["offset"] * 2
        end = (entity["offset"] + entity["length"]) * 2

        plain = buf[prev_end:start].decode("utf-16-le")
        if plain:
            result.append(_esc(plain))

        link_text = buf[start:end].decode("utf-16-le")
        url = entity["url"]
        result.append(f'<a href="{_html.escape(url)}">{_html.escape(link_text)}</a>')
        prev_end = end

    remaining = buf[prev_end:].decode("utf-16-le")
    if remaining:
        result.append(_esc(remaining))

    return "".join(result)


def apply_text_links(text: str, entities: list[dict]) -> str:
    """Вставляет URL из text_link-сущностей в текст: «слово» → «слово (url)».

    Telegram задаёт offset/length в UTF-16 code units (не в Python-символах),
    поэтому работаем через encode('utf-16-le').
    Обрабатываем сущности в обратном порядке, чтобы вставки не сдвигали позиции.
    """
    if not text or not entities:
        return text

    links = sorted(
        [e for e in entities if e.get("type") == "text_link" and e.get("url")],
        key=lambda e: e["offset"],
        reverse=True,
    )
    if not links:
        return text

    buf = text.encode("utf-16-le")
    for entity in links:
        start = entity["offset"] * 2       # байтовая позиция начала (2 байта на code unit)
        end = (entity["offset"] + entity["length"]) * 2
        linked_text = buf[start:end].decode("utf-16-le")
        replacement = f"{linked_text} ({entity['url']})".encode("utf-16-le")
        buf = buf[:start] + replacement + buf[end:]

    return buf.decode("utf-16-le")


def strip_trailing_time(text: str) -> str:
    """Убирает время в конце строки (HH:MM), оставляя символы/эмодзи после него.

    Примеры: "текст 05:56" → "текст", "текст 05:56 ❗️" → "текст ❗️"
    """
    if re.search(r"\d{2}:\d{2}\s*(?:[^\w\s]*)$", text):
        return re.sub(r"\s*\d{2}:\d{2}", "", text)
    return text
