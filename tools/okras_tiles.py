"""Фото окрасов для карточек и страниц окрасов: assets/img/okras-<порода>-<окрас>.jpg из студийных кадров.

python3 tools/okras_tiles.py   — нужен Pillow и numpy.

Правки клиента 15.10: на всех карточках окрасов щенок одного размера (примерно половина высоты кадра), по центру,
лапы на одной высоте, фон одного тона. Крупные кадры уменьшаются, фон вокруг достраивается продолжением
краёв кадра (студийный фон гладкий), новые кадры только центрируются. Собака не перекрашивается: тон фона
выравнивается только на пикселях фона (маска по насыщенности и оттенку), поэтому на шерсти нет ореолов.
Исходники не меняются; после запуска — замер фона в tools/photo-tones.json (tone_style берёт его оттуда).
"""
import pathlib

import numpy as np
from PIL import Image, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
IMG = ROOT / "assets" / "img"
SIZE = 1024
DOG_H = 0.50      # высота сидящего щенка, доля кадра
PAWS = 0.80       # где стоят лапы: у всех окрасов на одной высоте
WALL = np.array([246, 194, 155], float)   # тон стены: средний у кремового, рыжего, шоколадного и партиколор

# окрас → (исходник, рост щенка-ориентир: лежащему щенку не нужна та же высота)
SOURCES = {
    "maltipu": {
        "kremovyj": ("studio-maltipu-peach", 1), "belyj": ("color-maltipu-white", 1),
        "abrikosovyj": ("color-maltipu-apricot", 1), "ryzhij": ("color-maltipu-red", 1),
        "shokoladnyj": ("color-maltipu-chocolate", 1), "chernyj": ("color-maltipu-black", .78),
        "serebristyj": ("color-maltipu-silver", 1), "partikolor": ("color-maltipu-parti", 1),
        "fantom": ("color-maltipu-phantom", 1), "sobolinyj": ("color-maltipu-sable", 1),
    },
}


def backdrop_ref(a):
    """Цвет фона в каждой точке: по строке — между левым и правым краем кадра."""
    h, w, _ = a.shape
    e = int(w * .06)
    left, right = a[:, :e].mean(1), a[:, -e:].mean(1)
    t = np.linspace(0, 1, w)[None, :, None]
    return left[:, None, :] * (1 - t) + right[:, None, :] * t


def dog_box(a):
    """Щенок без тени: верх и низ (лапы) по строкам, центр по горизонтали — центр масс пикселей собаки."""
    d = np.sqrt(((a - backdrop_ref(a)) ** 2).sum(2))
    m = d > 60
    h, w = m.shape
    rows = np.where(m.sum(1) > w * .012)[0]
    cx = (m * np.arange(w)[None, :]).sum() / max(m.sum(), 1)
    return rows[0] / h, rows[-1] / h, cx / w


def extend(im, box):
    """Холст SIZE×SIZE: im ставится в box (x, y — может выходить за края), пустое — продолжение краёв кадра, размытое."""
    x, y = box
    w, h = im.size
    pad_l, pad_t = max(0, x), max(0, y)
    pad_r, pad_b = max(0, SIZE - (x + w)), max(0, SIZE - (y + h))
    a = np.asarray(im).astype(float)
    big = np.pad(a, ((pad_t, pad_b), (pad_l, pad_r), (0, 0)), mode="edge")
    # сдвиг внутрь холста, если кадр выходит за край
    big = big[max(0, -y):max(0, -y) + SIZE, max(0, -x):max(0, -x) + SIZE]
    out = Image.fromarray(np.clip(big, 0, 255).astype("uint8"))
    # продолжение краёв — полосами; размываем его и мягко сшиваем с кадром
    blur = np.asarray(out.filter(ImageFilter.GaussianBlur(28))).astype(float)
    mask = np.zeros((SIZE, SIZE), float)
    x0, y0 = max(0, x), max(0, y)
    mask[y0:min(SIZE, y + h), x0:min(SIZE, x + w)] = 1
    mask = np.asarray(Image.fromarray((mask * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(40))).astype(float) / 255
    res = big * mask[..., None] + blur * (1 - mask[..., None])
    return res


def tone_backdrop(a):
    """Тон фона к WALL: сдвиг только на пикселях фона (насыщенный тёплый персиковый), шерсть не трогаем."""
    ref = backdrop_ref(a)
    h = a.shape[0]
    wall = ref[int(h * .3):int(h * .55)].reshape(-1, 3).mean(0)
    shift = WALL - wall
    mx, mn = a.max(2), a.min(2)
    sat = (mx - mn) / np.maximum(mx, 1)
    ratio = (a[..., 1] - a[..., 2]) / np.maximum(a[..., 0] - a[..., 2], 1)
    wr = (wall[1] - wall[2]) / max(wall[0] - wall[2], 1)
    m = np.clip((sat - .12) / .08, 0, 1) * np.clip(1 - (np.abs(ratio - wr) - .1) / .15, 0, 1)
    m *= np.clip(1 - (np.sqrt(((a - ref) ** 2).sum(2)) - 18) / 30, 0, 1)   # далеко от фона строки — не фон
    return a + m[..., None] * shift


def make(src, height_k):
    im = Image.open(IMG / f"{src}.jpg").convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)
    a = np.asarray(im).astype(float)
    top, bottom, cx = dog_box(a)
    s = min(1.0, DOG_H * height_k / (bottom - top))
    w = round(SIZE * s)
    scaled = im.resize((w, w), Image.LANCZOS) if s < 1 else im
    # лапы — на PAWS, щенок — по центру
    y = round(SIZE * PAWS - bottom * w)
    x = round(SIZE / 2 - cx * w)
    out = extend(scaled, (x, y))
    return Image.fromarray(np.clip(np.round(tone_backdrop(out)), 0, 255).astype("uint8"))


if __name__ == "__main__":
    for breed, colours in SOURCES.items():
        for slug, (src, k) in colours.items():
            dest = IMG / f"okras-{breed}-{slug}.jpg"
            make(src, k).save(dest, "JPEG", quality=88, optimize=True, progressive=True)
            print(dest.relative_to(ROOT))
