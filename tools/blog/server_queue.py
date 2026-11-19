"""Read a private editorial schedule alongside the repository's ordinary blog feed.

content/blog/server-queue is optional and points outside the web root on the
production host. Its JSON and unpublished artwork are never release assets.
"""
import json
import re
import shutil
import tempfile
from datetime import date
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUEUE = ROOT / "content" / "blog" / "server-queue"
MEDIA_URL = "/assets/img/editorial-queue/"
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


@lru_cache(maxsize=1)
def schedule():
    if not QUEUE.is_dir():
        if QUEUE.is_symlink():
            raise FileNotFoundError(f"Missing editorial queue target: {QUEUE}")
        return {}
    records = json.loads((QUEUE / "schedule.json").read_text(encoding="utf-8"))["posts"]
    days = set()
    for slug, item in records.items():
        if not SLUG.fullmatch(slug):
            raise ValueError(f"Invalid editorial slug: {slug}")
        day = date.fromisoformat(item["date"])
        if day in days:
            raise ValueError(f"Duplicate editorial release date: {day}")
        days.add(day)
    return records


def merged(public):
    private = schedule()
    overlap = public.keys() & private.keys()
    if overlap:
        raise ValueError(f"Duplicate public and server article: {sorted(overlap)}")
    private_days = {record["date"] for record in private.values()}
    for slug, record in public.items():
        if record.get("series") == "main" and record["date"] in private_days:
            raise ValueError(f"Server editorial date already allocated: {record['date']} ({slug})")
    return {**public, **private}


def private_file(slug):
    return QUEUE / "posts" / f"{slug}.json"


def image_path(src):
    if not src.startswith(MEDIA_URL):
        return None
    name = src[len(MEDIA_URL):]
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*-[abcd]\.webp", name):
        raise ValueError(f"Invalid editorial image path: {src}")
    return QUEUE / "images" / name


def stage_images(live):
    """Only live files may enter assets/, which release.sh copies wholesale."""
    if not QUEUE.is_dir():
        return
    destination = ROOT / MEDIA_URL.strip("/")
    expected = {f"{slug}-{suffix}.webp" for slug in live for suffix in "abcd"}
    if not expected and not destination.exists():
        return
    destination.mkdir(parents=True, exist_ok=True)
    for name in sorted(expected):
        source, target = QUEUE / "images" / name, destination / name
        info = source.stat()
        if target.is_file() and (target.stat().st_mtime_ns, target.stat().st_size) == (info.st_mtime_ns, info.st_size):
            continue
        with tempfile.NamedTemporaryFile(dir=destination, suffix=".part", delete=False) as handle:
            temp = Path(handle.name)
        try:
            shutil.copy2(source, temp)
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
    for old in destination.glob("*.webp"):
        if old.name not in expected:
            old.unlink()
