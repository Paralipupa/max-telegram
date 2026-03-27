from __future__ import annotations

from typing import Optional

from max_message_extractors import (
    extract_attachment_items,
    extract_emojis,
    extract_image_urls,
    extract_text_caption,
    merge_caption_and_emojis,
)


async def extract_stable_message_id(bubble) -> Optional[str]:
    """DOM id for dedup when present (content-based hash is unstable for signed URLs)."""
    raw = await bubble.evaluate(
        """(el) => {
          const attrs = ["data-message-id", "data-id", "data-mid", "data-local-id"];
          const walk = (node) => {
            if (!node || node.nodeType !== 1) return "";
            for (const a of attrs) {
              const v = node.getAttribute(a);
              if (v && String(v).trim()) return String(v).trim();
            }
            const id = node.id;
            if (id && String(id).trim()) return String(id).trim();
            return "";
          };
          let s = walk(el);
          if (s) return s;
          const p = el.closest("[data-message-id],[data-id],[data-mid]");
          return p ? walk(p) : "";
        }"""
    )
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return None


def _with_stable_id(d: dict, stable_id: Optional[str]) -> dict:
    if stable_id:
        d["stable_id"] = stable_id
    return d


async def bubble_to_message_info(bubble) -> Optional[dict]:
    """Parses one MAX bubble into a message info dict.

    - text: {'type': 'text', 'text': '...'}
    - images: {'type': 'images', 'urls': [...], 'caption': '...'}
    - attachments: files/video (not img): {'type': 'attachments', 'items': [...], 'caption': '...'}
    - mixed: photo(s) + file(s): {'type': 'mixed', 'image_urls', 'attachments', 'caption'}
    """
    image_urls = await extract_image_urls(bubble)
    attachment_items = await extract_attachment_items(bubble)
    caption = await extract_text_caption(bubble)
    emojis = await extract_emojis(bubble)
    caption = merge_caption_and_emojis(caption, emojis)
    stable_id = await extract_stable_message_id(bubble)

    if image_urls and attachment_items:
        return _with_stable_id(
            {
                "type": "mixed",
                "image_urls": image_urls,
                "attachments": attachment_items,
                "caption": caption,
            },
            stable_id,
        )
    if image_urls:
        return _with_stable_id(
            {"type": "images", "urls": image_urls, "caption": caption},
            stable_id,
        )
    if attachment_items:
        return _with_stable_id(
            {"type": "attachments", "items": attachment_items, "caption": caption},
            stable_id,
        )
    if caption:
        return _with_stable_id({"type": "text", "text": caption}, stable_id)
    return None

