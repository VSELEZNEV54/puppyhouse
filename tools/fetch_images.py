"""Скачивает сгенерированные фото (tools/images.json) в assets/img/ как JPEG.

Запуск: python3 tools/fetch_images.py
Нужен доступ к www.figma.com. Ссылки действуют 7 дней с 12.10.2026.
"""
import io
import json
import pathlib
import urllib.request

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "img"
OUT.mkdir(parents=True, exist_ok=True)

for item in json.loads((ROOT / "tools" / "images.json").read_text(encoding="utf-8")):
    with urllib.request.urlopen(item["url"], timeout=60) as resp:
        data = resp.read()
    img = Image.open(io.BytesIO(data)).convert("RGB")
    dest = OUT / f"{item['name']}.jpg"
    img.save(dest, "JPEG", quality=88, optimize=True, progressive=True, subsampling=0)
    print(f"{dest.relative_to(ROOT)}  {img.width}x{img.height}  {dest.stat().st_size // 1024} KB")
