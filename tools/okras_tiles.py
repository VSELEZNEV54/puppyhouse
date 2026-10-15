"""Фото окрасов для карточек и страниц окрасов: assets/img/okras-<порода>-<окрас>.jpg из студийных кадров.

python3 tools/okras_tiles.py   — нужен Pillow и numpy.

Правки клиента 15.10: на всех карточках окрасов щенок одного размера (примерно половина высоты кадра), по центру,
лапы на одной высоте, фон одного тона. Крупные кадры уменьшаются, фон вокруг достраивается продолжением
краёв кадра (студийный фон гладкий), мелкие немного увеличиваются (не больше чем в 1,25 раза). Собака
не перекрашивается: тон фона выравнивается только на пикселях фона (маска по цветности и оттенку стены),
поэтому на шерсти нет ореолов.
Позы разные (сидит, стоит боком, лежит, сидит спиной и оглядывается): у лежащего и стоящего щенка ориентир
роста меньше (второе число в SOURCES).

Второй кадр каждого окраса — okras-<порода>-<окрас>-big.jpg для первого экрана страницы окраса: тот же щенок
крупно (около двух третей высоты кадра, лапы у нижнего края), кадр немного увеличивается, если щенок мелкий.
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
BIG = dict(dog_h=0.66, paws=0.90, max_w=0.84, max_up=1.7)   # крупный кадр для первого экрана страницы окраса

# тон стены у каждой породы — средний по её кадрам (фон в цвет плиток породы: персик, голубой, шалфей, масло)
WALLS = {
    "maltipu": (246, 194, 155),
    "buldog": (175, 207, 229),
    "kolli": (170, 187, 168),
    "pudel": (239, 211, 156),
}

# окрас → (исходник, рост щенка-ориентир: лежащему и стоящему боком щенку не нужна та же высота)
SOURCES = {
    "maltipu": {
        "kremovyj": ("studio-maltipu-peach", 1), "belyj": ("color-maltipu-white", 1),
        "abrikosovyj": ("color-maltipu-apricot", 1), "ryzhij": ("colsrc-maltipu-ryzhij", .9),
        "shokoladnyj": ("colsrc-maltipu-shokoladnyj", 1), "chernyj": ("color-maltipu-black", .78),
        "serebristyj": ("color-maltipu-silver", 1), "partikolor": ("color-maltipu-parti", 1),
        "fantom": ("color-maltipu-phantom", 1), "sobolinyj": ("color-maltipu-sable", 1),
    },
    "buldog": {
        "palevyj": ("colsrc-buldog-palevyj", 1), "tigrovyj": ("colsrc-buldog-tigrovyj", .72),
        "pegij": ("colsrc-buldog-pegij", .85), "goluboj": ("colsrc-buldog-goluboj", 1),
        "kremovyj": ("colsrc-buldog-kremovyj", .66), "shokoladnyj": ("colsrc-buldog-shokoladnyj", 1),
        "mramornyj": ("colsrc-buldog-mramornyj", 1),
    },
    "pudel": {
        "abrikosovyj": ("colsrc-pudel-abrikosovyj", 1), "chernyj": ("colsrc-pudel-chernyj", .9),
        "belyj": ("colsrc-pudel-belyj", .82), "korichnevyj": ("colsrc-pudel-korichnevyj", 1),
        "ryzhij": ("colsrc-pudel-ryzhij", 1), "seryj": ("colsrc-pudel-seryj", 1),
    },
    "kolli": {
        "goluboj-mramor": ("colsrc-kolli-goluboj-mramor", 1), "trehcvetnyj": ("colsrc-kolli-trehcvetnyj", .82),
        "krasno-belyj": ("colsrc-kolli-krasno-belyj", .88), "cherno-belyj": ("colsrc-kolli-cherno-belyj", 1),
        "krasnyj-mramor": ("colsrc-kolli-krasnyj-mramor", 1), "mramornyj-trikolor": ("colsrc-kolli-mramornyj-trikolor", .7),
        "lilovyj": ("colsrc-kolli-lilovyj", 1),
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
    """Щенок без тени: верх и низ (лапы) по строкам, центр по горизонтали — центр масс пикселей собаки, ширина."""
    d = np.sqrt(((a - backdrop_ref(a)) ** 2).sum(2))
    m = d > 60
    h, w = m.shape
    rows = np.where(m.sum(1) > w * .012)[0]
    cols = np.where(m.sum(0) > h * .012)[0]
    cx = (m * np.arange(w)[None, :]).sum() / max(m.sum(), 1)
    return rows[0] / h, rows[-1] / h, cx / w, (cols[-1] - cols[0]) / w


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


def tone_backdrop(a, target):
    """Тон фона к target: сдвиг только на пикселях фона (цвет и насыщенность как у стены, близко к фону строки),
    шерсть не трогаем. Цветность — отклонение от серого: у шерсти (серой, белой, кремовой) она другая по силе или оттенку."""
    ref = backdrop_ref(a)
    h = a.shape[0]
    wall = ref[int(h * .3):int(h * .55)].reshape(-1, 3).mean(0)
    shift = np.asarray(target, float) - wall
    cw = wall - wall.mean()
    c = a - a.mean(2, keepdims=True)
    size = np.sqrt((c ** 2).sum(2)) / max(np.sqrt((cw ** 2).sum()), 1)
    cos = (c * cw).sum(2) / np.maximum(np.sqrt((c ** 2).sum(2)) * np.sqrt((cw ** 2).sum()), 1e-6)
    m = np.clip((size - .45) / .25, 0, 1) * np.clip((cos - .82) / .12, 0, 1)
    m *= np.clip(1 - (np.sqrt(((a - ref) ** 2).sum(2)) - 18) / 30, 0, 1)   # далеко от фона строки — не фон
    return a + m[..., None] * shift


def make(src, height_k, wall, dog_h=DOG_H, paws=PAWS, max_w=1.0, max_up=1.25):
    im = Image.open(IMG / f"{src}.jpg").convert("RGB").resize((SIZE, SIZE), Image.LANCZOS)
    a = np.asarray(im).astype(float)
    top, bottom, cx, width = dog_box(a)
    s = min(max_up, dog_h * height_k / (bottom - top), max_w / width)
    w = round(SIZE * s)
    scaled = im.resize((w, w), Image.LANCZOS) if s != 1 else im
    # лапы — на paws, щенок — по центру
    y = round(SIZE * paws - bottom * w)
    x = round(SIZE / 2 - cx * w)
    out = extend(scaled, (x, y))
    return Image.fromarray(np.clip(np.round(tone_backdrop(out, wall)), 0, 255).astype("uint8"))


if __name__ == "__main__":
    for breed, colours in SOURCES.items():
        for slug, (src, k) in colours.items():
            for suffix, opts in (("", {}), ("-big", BIG)):
                dest = IMG / f"okras-{breed}-{slug}{suffix}.jpg"
                make(src, k, WALLS[breed], **opts).save(dest, "JPEG", quality=88, optimize=True, progressive=True)
                print(dest.relative_to(ROOT))
