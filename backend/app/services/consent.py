"""Consent documents from src/data/consent.json → consent_versions (append-only), and consent proof rows."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Consent, ConsentVersion


class ConsentError(RuntimeError):
    pass


def digest(doc: dict) -> str:
    canon = json.dumps({"title": doc["title"], "checkbox": doc["checkbox"], "body": doc["body"]},
                       ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canon.encode()).hexdigest()


@lru_cache
def load(path: Path | None = None) -> dict:
    p = Path(path or get_settings().consent_file)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ConsentError(f"cannot read {p}: {e}") from e
    versions = {v["version"]: v for v in data.get("versions", [])}
    for kind, ver in (data.get("current") or {}).items():
        if ver not in versions or versions[ver]["kind"] != kind:
            raise ConsentError(f"consent.json: current {kind} version {ver!r} is not among the versions")
    if "processing" not in (data.get("current") or {}):
        raise ConsentError("consent.json: no current processing consent")
    return {"current": data["current"], "versions": versions}


def current(kind: str) -> str:
    return load()["current"][kind]


def sync(db: Session) -> dict:
    """Insert new versions; refuse to change the text of a published one (people agreed to that exact text)."""
    docs = load()["versions"]
    have = {v.version: v for v in db.scalars(select(ConsentVersion))}
    added = []
    for ver, doc in docs.items():
        h = digest(doc)
        row = have.get(ver)
        if row is None:
            db.add(ConsentVersion(version=ver, kind=doc["kind"], title=doc["title"], url=doc["url"],
                                  checkbox_text=doc["checkbox"], body="\n\n".join(doc["body"]), text_sha256=h))
            added.append(ver)
        elif row.text_sha256 != h:
            raise ConsentError(f"consent version {ver} was edited after publication — add a new version instead")
    db.flush()
    return {"consent_versions_added": added}


def record(db: Session, *, version: str, contact_id: int | None = None, lead_id: int | None = None,
           review_id: int | None = None, page_path: str | None, ip: str | None, user_agent: str | None) -> Consent:
    c = Consent(version=version, contact_id=contact_id, lead_id=lead_id, review_id=review_id, page_path=page_path,
                ip=ip, user_agent=user_agent)
    db.add(c)
    return c
