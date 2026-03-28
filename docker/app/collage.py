"""Сборка коллажа из нескольких фото в стиле Telegram."""

import io
from PIL import Image

COLLAGE_WIDTH = 1200  # итоговая ширина коллажа в пикселях
GAP = 4               # зазор между фото


def _layout(n: int) -> list[list[int]]:
    """Разбивка N фото по строкам (индексы)."""
    if n == 1:
        return [[0]]
    if n == 2:
        return [[0, 1]]
    if n == 3:
        return [[0], [1, 2]]
    if n == 4:
        return [[0, 1], [2, 3]]
    if n == 5:
        return [[0], [1, 2], [3, 4]]
    if n == 6:
        return [[0, 1, 2], [3, 4, 5]]
    # 7+: первое фото на всю ширину, остальные по 3 в строку
    rows: list[list[int]] = [[0]]
    rest = list(range(1, n))
    for i in range(0, len(rest), 3):
        rows.append(rest[i : i + 3])
    return rows


def _make_row(images: list[Image.Image], width: int) -> Image.Image:
    """Склеивает фото в горизонтальную полосу заданной ширины."""
    n = len(images)
    total_aspect = sum(im.width / im.height for im in images)
    row_h = int((width - GAP * (n - 1)) / total_aspect)

    row = Image.new("RGB", (width, row_h))
    x = 0
    for i, im in enumerate(images):
        w = width - x if i == n - 1 else int(im.width / im.height * row_h)
        row.paste(im.resize((w, row_h), Image.LANCZOS), (x, 0))
        x += w + GAP
    return row


def make_collage(paths: list[str]) -> bytes:
    """Создаёт коллаж из файлов изображений и возвращает JPEG-байты."""
    imgs = [Image.open(p).convert("RGB") for p in paths]
    rows_idx = _layout(len(imgs))

    row_imgs = [_make_row([imgs[i] for i in row], COLLAGE_WIDTH) for row in rows_idx]

    total_h = sum(r.height for r in row_imgs) + GAP * (len(row_imgs) - 1)
    canvas = Image.new("RGB", (COLLAGE_WIDTH, total_h))
    y = 0
    for row_img in row_imgs:
        canvas.paste(row_img, (0, y))
        y += row_img.height + GAP

    buf = io.BytesIO()
    canvas.save(buf, format="JPEG", quality=85)
    return buf.getvalue()
