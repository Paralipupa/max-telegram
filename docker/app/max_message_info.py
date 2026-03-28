from __future__ import annotations

from typing import Optional

from max_message_extractors import (
    extract_attachment_items,
    extract_emojis,
    extract_image_urls,
    extract_text_caption,
    merge_caption_and_emojis,
)


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

    if image_urls and attachment_items:
        return {
            "type": "mixed",
            "image_urls": image_urls,
            "attachments": attachment_items,
            "caption": caption,
        }
    if image_urls:
        return {"type": "images", "urls": image_urls, "caption": caption}
    if attachment_items:
        return {"type": "attachments", "items": attachment_items, "caption": caption}
    if caption:
        return {"type": "text", "text": caption}
    return None

