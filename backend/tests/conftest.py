"""Tests run against a real PostgreSQL. Each pytest process creates its own database (dsh_test_<pid>), builds it
with `python -m app migrate` (alembic + consent + catalog + views) and drops it at the end.

    DSH_TEST_DATABASE_URL  any database on the server, used to create the test one
                           (default postgresql+psycopg://dsh:dsh@localhost:5432/postgres; the user needs CREATEDB)
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BASE_URL = os.environ.get("DSH_TEST_DATABASE_URL", "postgresql+psycopg://dsh:dsh@localhost:5432/postgres")
TEST_DB = f"dsh_test_{os.getpid()}"
TEST_URL = make_url(BASE_URL).set(database=TEST_DB).render_as_string(hide_password=False)

# settings are read at import time of app.*: configure the environment first
os.environ.update({
    "DSH_ENV": "test",
    "DSH_DATABASE_URL": TEST_URL,
    "DSH_TELEGRAM_BOT_TOKEN": "",
    "DSH_WEBHOOK_URL": "",
    "DSH_SMTP_HOST": "",
})

# the consent versions the site shows now (src/data/consent.json → current); tests never hard-code a date
REPO_DATA_CONSENT = Path(__file__).resolve().parents[2] / "src" / "data" / "consent.json"
CONSENT_CURRENT = json.loads(REPO_DATA_CONSENT.read_text(encoding="utf-8"))["current"]

KEEP = {"breeds", "puppies", "consent_versions", "alembic_version"}


def _admin_engine():
    return create_engine(BASE_URL, isolation_level="AUTOCOMMIT")


@pytest.fixture(scope="session", autouse=True)
def database():
    eng = _admin_engine()
    with eng.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
        c.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    from app.__main__ import main
    assert main(["migrate"]) == 0
    yield TEST_URL
    from app.db import get_engine
    get_engine().dispose()
    with eng.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
    eng.dispose()


@pytest.fixture(autouse=True)
def clean(database):
    """Empty every table except the catalog before each test."""
    from app.db import get_engine
    from app.models import Base
    tables = [t.name for t in Base.metadata.sorted_tables if t.name not in KEEP]
    with get_engine().begin() as c:
        c.execute(text("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
def settings():
    """The live Settings object; attributes changed in a test are restored afterwards."""
    from app.config import get_settings
    s = get_settings()
    saved = s.model_dump()
    yield s
    for k, v in saved.items():
        object.__setattr__(s, k, v)


@pytest.fixture
def db():
    from app.db import _factory
    session = _factory()()
    yield session
    session.rollback()
    session.close()


ORIGIN = "https://xn--b1adduihee9g.xn--p1ai"


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app, client=("203.0.113.10", 50000), headers={"Origin": ORIGIN}) as c:
        yield c


def lead_payload(**over) -> dict:
    """A valid request as main.js sends it; override any field."""
    p = {
        "kind": "price", "name": "Анна", "phone": "+7 (999) 123-45-67", "contact": "telegram", "consent": True,
        "consent_version": CONSENT_CURRENT["processing"], "breed": "maltipu", "page": {"path": "/maltipu/", "title": "Мальтипу"},
        "visitor_id": str(uuid.uuid4()), "session_id": str(uuid.uuid4()), "idempotency_key": str(uuid.uuid4()),
        "elapsed_ms": 20_000, "hp_note": "",
    }
    p.update(over)
    return p


@pytest.fixture
def make_lead(client):
    def _make(**over):
        r = client.post("/api/v1/leads", json=lead_payload(**over))
        assert r.status_code in (200, 201), r.text
        return r.json()
    return _make


@pytest.fixture
def admin_user(db):
    from app.enums import Role
    from app.services import auth
    u = auth.create_user(db, "anna", "Анна", Role.admin, "очень-длинный-пароль-1")
    db.commit()
    return u


@pytest.fixture
def manager_user(db):
    from app.enums import Role
    from app.services import auth
    u = auth.create_user(db, "oleg", "Олег", Role.manager, "очень-длинный-пароль-2")
    db.commit()
    return u


def _login(client, login, password):
    r = client.post("/api/v1/admin/auth/login", json={"login": login, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture
def admin_h(client, admin_user):
    return _login(client, "anna", "очень-длинный-пароль-1")


@pytest.fixture
def manager_h(client, manager_user):
    return _login(client, "oleg", "очень-длинный-пароль-2")
