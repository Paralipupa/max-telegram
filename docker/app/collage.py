"""Сборка коллажа из нескольких фото в стиле Telegram."""

import io
from PIL import Image

# Итоговая ширина коллажа в пикселях
COLLAGE_WIDTH = 1200
# Зазор между фото
GAP = 4
# Минимальная высота строки (защита от слишком тонких строк при экстремальных пропорциях)
MIN_ROW_HEIGHT = 80
# Максимум фото в строке (кроме одиночного первого)
MAX_PER_ROW = 3


def _layout(n: int) -> list[list[int]]:
    """Разбивка N фото по строкам (индексы).
    Первое фото отдельно (на всю ширину) для N=3,5,7+.
    """
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
    # 7+: первое фото на всю ширину, остальные по MAX_PER_ROW в строку
    rows: list[list[int]] = [[0]]
    rest = list(range(1, n))
    for i in range(0, len(rest), MAX_PER_ROW):
        rows.append(rest[i : i + MAX_PER_ROW])
    return rows


def _make_row(images: list[Image.Image], width: int) -> Image.Image:
    """Склеивает фото в горизонтальную полосу заданной ширины.

    Высота строки рассчитывается так, чтобы все фото вписались по ширине
    с сохранением пропорций: row_h = (width - gaps) / sum(w_i/h_i).
    """
    n = len(images)
    total_aspect = sum(im.width / im.height for im in images)
    row_h = max(MIN_ROW_HEIGHT, int((width - GAP * (n - 1)) / total_aspect))

    # Вычисляем ширину каждого фото и остаток отдаём последнему (компенсация округления)
    widths = [int(im.width / im.height * row_h) for im in images]
    used = sum(widths) + GAP * (n - 1)
    widths[-1] += width - used  # last photo absorbs rounding delta

    row = Image.new("RGB", (width, row_h))
    x = 0
    for im, w in zip(images, widths):
        w = max(1, w)  # защита от нулевой ширины
        row.paste(im.resize((w, row_h), Image.Resampling.LANCZOS), (x, 0))
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
