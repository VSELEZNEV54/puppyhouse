"""Breeds, puppies and colours come from the static site's data files (src/data/*.json): the site is the source of
truth for the catalog. `sync()` upserts them into the database so requests can reference a breed and a puppy.

Rules: nothing is ever deleted (requests point at it). Breeds match by their stable `key`, puppies by `slug`.
A breed or puppy that disappears from the JSON is deactivated; a puppy that disappears is also marked «sold».
The sync refuses to run on an empty catalog or when it would deactivate more than half of the active puppies
(a truncated file), unless forced. Per-breed views are rebuilt at the end."""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..config import get_settings
from ..enums import PuppyStatus
from ..models import Breed, Puppy
from . import views

UNDECIDED = "Пока не решил(а)"
_WS = re.compile(r"\s+")
UTC = dt.timezone.utc


class CatalogError(RuntimeError):
    pass


def norm(s: str | None) -> str:
    """Case-, ё- and space-insensitive key (the select sends «Пока не&nbsp;решил(а)» with a non-breaking space)."""
    return _WS.sub(" ", (s or "").replace("\u00a0", " ").replace("\u2060", "")).strip().lower().replace("ё", "е")


@dataclass
class SiteCatalog:
    breeds: list[dict]
    puppies: list[dict]
    colours: dict[str, dict[str, str]] = field(default_factory=dict)  # breed slug → {colour slug: label}

    def breed_by_any(self, value: str | None) -> dict | None:
        """Breed by slug, key or Russian name; None for empty / «Пока не решил(а)» / unknown."""
        k = norm(value)
        if not k or k == norm(UNDECIDED):
            return None
        for b in self.breeds:
            if k in (b["slug"], b["key"], norm(b["name"])):
                return b
        return None

    def colour_label(self, breed_slug: str | None, colour: str | None) -> str | None:
        if not colour:
            return None
        if breed_slug:
            return self.colours.get(breed_slug, {}).get(colour)
        for cols in self.colours.values():
            if colour in cols:
                return cols[colour]
        return None


def _colours(breedsub: dict) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}

    def walk(node, slug):
        if isinstance(node, dict):
            if isinstance(node.get("slug"), str) and "pick" in node:  # colour items: «подобрать кремового мальтипу»
                out.setdefault(slug, {})[node["slug"]] = node.get("name") or node.get("title") or node["slug"]
            for v in node.values():
                walk(v, slug)
        elif isinstance(node, list):
            for v in node:
                walk(v, slug)

    for slug, v in breedsub.items():
        if not slug.startswith("_") and slug != "common":
            walk(v, slug)
    return out


@lru_cache
def load(data_dir: Path | None = None) -> SiteCatalog:
    """Read and validate the JSON files. Cached: restart the API (or call load.cache_clear()) after a site deploy."""
    d = Path(data_dir or get_settings().site_data_dir)
    try:
        breeds = json.loads((d / "breeds.json").read_text(encoding="utf-8"))
        puppies = json.loads((d / "puppies.json").read_text(encoding="utf-8"))
        sub_path = d / "breedsub.json"
        colours = _colours(json.loads(sub_path.read_text(encoding="utf-8"))) if sub_path.is_file() else {}
    except (OSError, ValueError) as e:
        raise CatalogError(f"cannot read the site catalog in {d}: {e}") from e
    if not isinstance(breeds, list) or not breeds:
        raise CatalogError("breeds.json is empty")
    if not isinstance(puppies, list):
        raise CatalogError("puppies.json must be a list")
    keys = set()
    for b in breeds:
        for f in ("slug", "key", "name"):
            if not isinstance(b.get(f), str) or not b[f]:
                raise CatalogError(f"breeds.json: a breed without {f}: {b!r:.120}")
        views.view_name(b["key"])  # validates the key format
        keys.add(b["slug"])
    for p in puppies:
        for f in ("slug", "name", "breed", "status"):
            if not isinstance(p.get(f), str) or not p[f]:
                raise CatalogError(f"puppies.json: a puppy without {f}: {p.get('slug')!r}")
        if p["breed"] not in keys:
            raise CatalogError(f"puppies.json: {p['slug']}: unknown breed {p['breed']!r}")
    return SiteCatalog(breeds=breeds, puppies=puppies, colours=colours)


def sync(db: Session, catalog: SiteCatalog | None = None, force: bool = False) -> dict:
    """Upsert breeds and puppies (in the caller's transaction) and rebuild the per-breed views."""
    cat = catalog or load()
    now = dt.datetime.now(UTC)
    stats: dict = {"breeds": 0, "breeds_deactivated": 0, "puppies": 0, "puppies_new": 0, "puppies_deactivated": 0}

    active_pups = db.scalar(select(func.count()).select_from(Puppy).where(Puppy.is_active.is_(True))) or 0
    json_slugs = {p["slug"] for p in cat.puppies}
    gone = db.scalar(select(func.count()).select_from(Puppy)
                     .where(Puppy.is_active.is_(True), Puppy.slug.not_in(json_slugs or {""}))) or 0
    if not force:
        if not cat.puppies and active_pups:
            raise CatalogError("puppies.json has no puppies — refusing to deactivate the whole catalog (use --force)")
        if active_pups >= 4 and gone * 2 > active_pups:
            raise CatalogError(f"{gone} of {active_pups} active puppies would be deactivated — "
                               "is puppies.json truncated? (use --force)")

    existing = list(db.scalars(select(Breed)))
    by_key = {b.key: b for b in existing}
    by_slug = {b.slug: b for b in existing}
    for i, b in enumerate(cat.breeds):
        row = by_key.get(b["key"])
        if row is None and b["slug"] in by_slug:  # the key was renamed in breeds.json: keep the row and its requests
            row = by_slug[b["slug"]]
            row.key = b["key"]
        if row is None:
            row = Breed(key=b["key"], slug=b["slug"], name=b["name"], sort=i, first_seen_at=now)
            db.add(row)
        row.slug, row.name, row.sort, row.is_active, row.deactivated_at, row.synced_at = (
            b["slug"], b["name"], i, True, None, now)
        stats["breeds"] += 1
    db.flush()
    stats["breeds_deactivated"] = db.execute(
        update(Breed).where(Breed.key.not_in({b["key"] for b in cat.breeds}), Breed.is_active.is_(True))
        .values(is_active=False, deactivated_at=now)).rowcount
    breed_ids = {b.slug: b.id for b in db.scalars(select(Breed).where(Breed.is_active.is_(True)))}

    pups = {p.slug: p for p in db.scalars(select(Puppy))}
    for p in cat.puppies:
        row = pups.get(p["slug"])
        if row is None:
            row = Puppy(slug=p["slug"], breed_id=breed_ids[p["breed"]], name=p["name"], status=p["status"],
                        first_seen_at=now)
            db.add(row)
            stats["puppies_new"] += 1
        row.breed_id = breed_ids[p["breed"]]
        row.name = p["name"][:100]
        row.sex = p.get("sex") if p.get("sex") in ("male", "female") else None
        row.colour = (p.get("colour") or None) and str(p["colour"])[:60]
        row.generation = (p.get("generation") or None) and str(p["generation"])[:20]
        try:
            row.birth_date = dt.date.fromisoformat(p["birth_date"]) if p.get("birth_date") else None
        except ValueError:
            row.birth_date = None
        row.status = p["status"] if p["status"] in PuppyStatus.__members__ else PuppyStatus.available.value
        row.is_active, row.deactivated_at, row.synced_at = True, None, now
        stats["puppies"] += 1
    db.flush()
    stats["puppies_deactivated"] = db.execute(
        update(Puppy).where(Puppy.slug.not_in(json_slugs or {""}), Puppy.is_active.is_(True))
        .values(is_active=False, deactivated_at=now, status=PuppyStatus.sold.value)).rowcount
    stats["views"] = views.rebuild(db)
    return stats
