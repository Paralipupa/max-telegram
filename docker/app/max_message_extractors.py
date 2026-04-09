from __future__ import annotations

from typing import Any, Optional


async def extract_image_urls(bubble) -> list[str]:
    """Extracts image URLs from a MAX message bubble."""
    imgs = await bubble.query_selector_all("span.media img")
    if not imgs:
        imgs = await bubble.query_selector_all("div.media img")
    urls: list[str] = []
    for img in imgs:
        src = await img.get_attribute("src")
        # пропускаем base64-заглушки (1x1 пиксель для Lottie-анимаций)
        if src and not src.startswith("data:image"):
            urls.append(src)
    return urls

async def extract_attachment_items(bubble) -> list[dict[str, Any]]:
    """Non-image attachments: file links and video sources inside a bubble.

    MAX often renders files as ``<a href>`` under ``div.media`` / ``.attach``;
    photos use ``<img>`` (handled by :func:`extract_image_urls`). Image ``src``
    values are resolved in the page context so they match link URLs.
    """
    raw = await bubble.evaluate(
        """(el) => {
          const exclude = new Set();
          el.querySelectorAll("div.media img").forEach((img) => {
            if (img.src) {
              try {
                exclude.add(new URL(img.src, location.href).href);
              } catch (e) {}
            }
          });
          const items = [];
          const seen = new Set();
          const push = (url, kind, name) => {
            if (!url || url.startsWith("blob:") || url.startsWith("data:")) return;
            let abs;
            try {
              abs = new URL(url, location.href).href;
            } catch (e) {
              return;
            }
            if (exclude.has(abs) || seen.has(abs)) return;
            seen.add(abs);
            items.push({ url: abs, kind, name: name || "" });
          };
          el.querySelectorAll(
            "div.media video, .attach video, .attaches video"
          ).forEach((v) => {
            if (v.currentSrc) push(v.currentSrc, "video", "");
            if (v.src) push(v.src, "video", "");
            v.querySelectorAll("source[src]").forEach((s) => {
              if (s.src) push(s.src, "video", "");
            });
          });
          const linkSel =
            "div.media a[href], .attach a[href], .attaches a[href], " +
            'a[download][href], [class*="file"] a[href]';
          el.querySelectorAll(linkSel).forEach((a) => {
            const href = a.getAttribute("href");
            if (!href || href.startsWith("#") || href.startsWith("javascript:")) return;
            if (a.querySelector && a.querySelector("img")) return;
            const name = (a.innerText || "").trim();
            push(href, "document", name);
          });
          return items;
        }"""
    )
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for it in raw:
        if not isinstance(it, dict):
            continue
        url = it.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        kind = it.get("kind") or "document"
        if kind not in ("document", "video"):
            kind = "document"
        name = it.get("name") if isinstance(it.get("name"), str) else ""
        out.append({"url": url.strip(), "kind": kind, "name": name.strip()})
    return out


async def extract_sender(bubble) -> dict:
    """Определяет отправителя сообщения.

    Возвращает {'is_outgoing': bool, 'name': str|None}.
    Направление берётся из data-bubbles-variant="outgoing/incoming" внутри пузыря.
    Имя отправителя для входящих ищется в ближайшем messageWrapper (может быть None
    в личных чатах, где имя не показывается на каждом сообщении).
    """
    return await bubble.evaluate(
        """(el) => {
          // data-bubbles-variant — РОДИТЕЛЬ пузыря (bubble → bordersWrapper → div[data-bubbles-variant])
          const variantEl = el.closest('[data-bubbles-variant]');
          const variant = variantEl?.getAttribute('data-bubbles-variant');
          const isOutgoing = variant === 'outgoing';

          if (isOutgoing) return { is_outgoing: true, name: null };

          // Для входящих: ищем имя отправителя в messageWrapper
          const wrapper = el.closest('[class*="messageWrapper"]');
          if (!wrapper) return { is_outgoing: false, name: null };

          // В групповых чатах имя показывается в .name > .text рядом с сообщением
          const nameEl = wrapper.querySelector(
            '[class*="name"] [class*="text"], [class*="title"] [class*="text"]'
          );
          const name = nameEl ? (nameEl.innerText || '').trim() : null;
          return { is_outgoing: false, name: name || null };
        }"""
    )


async def extract_reply_quote(bubble) -> Optional[dict]:
    """Извлекает блок цитаты из reply-сообщения MAX.

    В DOM MAX reply-блок — это div[class*="link"] с button[class*="mark"] внутри.
    Автор цитаты — span[class*="author"], текст — span[class*="text"] в той же кнопке.
    Возвращает {'author': str, 'text': str} или None если это не reply.
    """
    return await bubble.evaluate(
        """(el) => {
          // Кнопка-цитата: div.link > button.mark
          const btn = el.querySelector(
            'div[class*="link"] button[class*="mark"]'
          );
          if (!btn) return null;

          const authorEl = btn.querySelector('[class*="author"]');
          const author = authorEl ? (authorEl.innerText || "").trim() : "";

          // Текст цитаты — span.text внутри кнопки, но не внутри author
          let text = "";
          btn.querySelectorAll('span[class*="text"]').forEach((span) => {
            if (authorEl && authorEl.contains(span)) return;
            const t = (span.textContent || "").replace(/\\s+/g, " ").trim();
            if (t) text = t;
          });

          return author || text ? { author, text } : null;
        }"""
    )


async def extract_text_caption(bubble) -> Optional[str]:
    """Извлекает текст основного сообщения, исключая блок цитаты (reply).

    Forwarded photo messages often split text across several spans or omit the
    exact class name ``text`` on the first node; ``read_message_text`` already
    uses a broader XPath — mirror that and aggregate spans, then fall back to
    bubble text with media/emoji nodes stripped so caption is not lost.
    """
    # Исключаем span.text, которые находятся внутри div.link (блок цитаты)
    text_spans = await bubble.query_selector_all(
        'xpath=.//span[contains(@class, "text")'
        ' and not(ancestor::div[contains(@class, "link")])'
        ' and not(ancestor::button[contains(@class, "mark")])]'
    )
    parts: list[str] = []
    for text_span in text_spans:
        t = await text_span.text_content()
        t = t.strip() if t else ""
        if t:
            parts.append(t)
    if parts:
        return " ".join(parts)

    # Фоллбек: весь текст пузыря без блока цитаты, медиа и эмодзи
    caption = await bubble.evaluate(
        """(el) => {
          const clone = el.cloneNode(true);
          // Удаляем reply-блок (div.link > button.mark)
          clone.querySelectorAll('div[class*="link"]').forEach((n) => n.remove());
          clone.querySelectorAll("div.media").forEach((n) => n.remove());
          clone.querySelectorAll("span.emoji").forEach((n) => n.remove());
          // Удаляем meta (время)
          clone.querySelectorAll('[class*="meta"]').forEach((n) => n.remove());
          const raw = (clone.innerText || "").replace(/\\s+/g, " ").trim();
          return raw || "";
        }"""
    )
    caption = caption.strip() if isinstance(caption, str) else ""
    return caption or None


async def extract_emojis(bubble) -> list[str]:
    """Extracts emojis from a MAX message bubble."""
    emoji_spans = await bubble.query_selector_all("span.emoji")
    emoji_chars: list[str] = []
    for emoji_span in emoji_spans:
        emoji_char = await emoji_span.get_attribute("data-lexical-emoji")
        if not emoji_char:
            img = await emoji_span.query_selector("img")
            if img:
                emoji_char = await img.get_attribute("alt")
        if emoji_char:
            emoji_chars.append(emoji_char)
    return emoji_chars


def merge_caption_and_emojis(caption: Optional[str], emojis: list[str]) -> Optional[str]:
    """Combines caption and emojis into a single text value."""
    if not emojis:
        return caption or None
    emoji_text = "".join(emojis)
    if caption:
        return f"{caption} {emoji_text}".strip()
    return emoji_text

