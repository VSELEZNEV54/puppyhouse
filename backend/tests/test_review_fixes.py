"""Regression tests for problems found by the adversarial review of the backend."""
from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select, text

from app.models import Contact, Lead
from app.services import admin_people, retention, views
from conftest import lead_payload

A = "/api/v1/admin"


def _lead(client, **over):
    r = client.post("/api/v1/leads", json=lead_payload(**over))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _id(db, public_id):
    return db.scalar(select(Lead.id).where(Lead.public_id == public_id))


def test_erase_closes_the_persons_open_requests(client, db, admin_h):
    lid = _id(db, _lead(client, phone="+7 900 111-00-01"))
    cid = db.scalar(select(Lead.contact_id).where(Lead.id == lid))
    r = client.post(f"{A}/contacts/{cid}/erase", json={"reason": "withdrawal", "subject": "Иванов"}, headers=admin_h)
    assert r.status_code == 200 and r.json()["counts"]["open_requests_closed"] == 1
    db.expire_all()
    lead = db.get(Lead, lid)
    assert (lead.status, lead.lost_reason) == ("lost", "other") and lead.closed_at and lead.anonymised_at
    assert client.get(f"{A}/leads", params={"status": "open"}, headers=admin_h).json()["total"] == 0


def test_comment_bumps_the_version_atomically(client, db, admin_h):
    lid = _id(db, _lead(client, phone="+7 900 111-00-02"))
    db.execute(text("UPDATE leads SET version = 7 WHERE id = :i"), {"i": lid})
    db.commit()
    d = client.post(f"{A}/leads/{lid}/comments", json={"text": "перезвонить"}, headers=admin_h).json()
    assert d["version"] == 8  # never computed from a stale copy


def test_merging_a_blocked_contact_keeps_the_number_blocked(client, db, admin_h):
    a = _id(db, _lead(client, phone="+7 900 111-00-03"))
    b = _id(db, _lead(client, phone="+7 900 111-00-04", breed="toj-pudel"))
    ca, cb = (db.scalar(select(Lead.contact_id).where(Lead.id == x)) for x in (a, b))
    assert client.patch(f"{A}/contacts/{ca}", json={"is_blocked": True}, headers=admin_h).status_code == 200
    assert client.post(f"{A}/contacts/{ca}/merge", json={"into_id": cb}, headers=admin_h).status_code == 200
    again = _id(db, _lead(client, phone="+7 900 111-00-03", breed="border-kolli"))
    db.expire_all()
    assert db.get(Lead, again).status == "spam" and db.get(Contact, cb).is_blocked


def test_a_repeat_request_taken_on_its_own_is_detached_from_its_parent(client, db, admin_h):
    p = _id(db, _lead(client, phone="+7 900 111-00-05"))
    c = _id(db, _lead(client, phone="+7 900 111-00-05", kind="video_call"))
    assert db.get(Lead, c).parent_id == p
    v = db.get(Lead, c).version
    r = client.patch(f"{A}/leads/{c}", json={"version": v, "status": "in_progress"}, headers=admin_h)
    assert r.status_code == 200 and r.json()["parent_id"] is None
    ids = [x["id"] for x in client.get(f"{A}/leads", params={"status": "open"}, headers=admin_h).json()["items"]]
    assert c in ids


def test_retention_erases_an_untouched_open_request_after_three_years(client, db):
    lid = _id(db, _lead(client, phone="+7 900 111-00-08"))  # status new, never worked
    db.execute(text("UPDATE contacts SET last_seen_at = now() - interval '4 years'"))
    db.execute(text("UPDATE leads SET last_activity_at = now() - interval '4 years'"))
    db.commit()
    assert retention.run(db)["contacts_erased"] == 1
    db.expire_all()
    assert db.get(Lead, lid).anonymised_at is not None and db.get(Lead, lid).status == "lost"


def test_retention_keeps_a_person_who_came_back_during_the_purge(client, db, settings):
    lid = _id(db, _lead(client, phone="+7 900 111-00-06"))
    cid = db.scalar(select(Lead.contact_id).where(Lead.id == lid))
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=settings.keep_contacts_days)
    # chosen as stale earlier, but the person is active now (last_seen_at = now) and has an open request
    assert admin_people.erase(db, cid, "retention", "x", None, "Система", stale_before=cutoff) is None
    db.expire_all()
    assert db.get(Contact, cid) is not None and db.get(Lead, lid).anonymised_at is None


def test_retention_still_erases_a_really_stale_contact(client, db, settings):
    lid = _id(db, _lead(client, phone="+7 900 111-00-07"))
    db.execute(text("UPDATE leads SET status = 'lost', lost_reason = 'other'"))
    db.execute(text("UPDATE contacts SET last_seen_at = now() - interval '4 years'"))
    db.execute(text("UPDATE leads SET last_activity_at = now() - interval '4 years'"))
    db.commit()
    assert retention.run(db)["contacts_erased"] == 1
    db.expire_all()
    assert db.get(Lead, lid).anonymised_at is not None


def test_a_failed_catalog_step_never_leaves_the_database_without_views(db, monkeypatch):
    from app import __main__ as cli
    from app.services import catalog

    def boom(*a, **k):
        raise catalog.CatalogError("simulated: puppies.json truncated")
    monkeypatch.setattr(catalog, "sync", boom)
    with pytest.raises(catalog.CatalogError):
        cli.main(["migrate"])
    names = {r[0] for r in db.execute(text("SELECT viewname FROM pg_views WHERE viewname LIKE 'leads\\_%'"))}
    assert {"leads_all", "leads_general", "leads_maltipu"} <= names


def test_readonly_role_gets_the_views_only(db):
    try:
        db.execute(text("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dsh_readonly') "
                        "THEN CREATE ROLE dsh_readonly; END IF; END $$"))
    except Exception:  # noqa: BLE001 — the test user may lack CREATEROLE
        pytest.skip("cannot create the dsh_readonly role here")
    views.rebuild(db)
    db.commit()
    can = lambda t: db.scalar(text("SELECT has_table_privilege('dsh_readonly', :t, 'SELECT')"), {"t": t})  # noqa: E731
    assert can("leads_maltipu") and can("leads_all")
    assert not can("admin_users") and not can("admin_tokens") and not can("contacts")
