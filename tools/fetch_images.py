"""Скачивает сгенерированные фото (tools/images.json) в assets/img/ как JPEG.

Запуск: python3 tools/fetch_images.py [--force] (или GitHub Actions: .github/workflows/fetch-images.yml).
Без --force качает только отсутствующие файлы.
Нужен доступ к www.figma.com. Ссылки действуют 7 дней с даты генерации.
"""
import io
import json
import pathlib
import sys
import urllib.request

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "img"
OUT.mkdir(parents=True, exist_ok=True)

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

FORCE = "--force" in sys.argv  # по умолчанию качаем только файлы, которых ещё нет

for item in json.loads((ROOT / "tools" / "images.json").read_text(encoding="utf-8")):
    if not FORCE and (OUT / f"{item['name']}.jpg").exists():
        continue
    req = urllib.request.Request(item["url"], headers={"User-Agent": UA, "Accept": "image/avif,image/webp,image/png,image/*,*/*"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
        ctype = resp.headers.get("Content-Type")
    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        print(f"{item['name']}: not an image, content-type={ctype}, {len(data)} bytes")
        raise
    dest = OUT / f"{item['name']}.jpg"
    img.save(dest, "JPEG", quality=88, optimize=True, progressive=True, subsampling=0)
    print(f"{dest.relative_to(ROOT)}  {img.width}x{img.height}  {dest.stat().st_size // 1024} KB")
