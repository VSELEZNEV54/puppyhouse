"""End-to-end smoke test: one request from the site reaches the per-breed base and the admin API."""
from sqlalchemy import text

from conftest import lead_payload


def test_request_lands_in_breed_view_and_admin_list(client, db, admin_h):
    r = client.post("/api/v1/leads", json=lead_payload(kind="colour", colour="kremovyj", note="Окрас: кремовый",
                                                        page={"path": "/puppyhouse/maltipu/kremovyj/?utm_source=x"}))
    assert r.status_code == 201, r.text

    rows = db.execute(text("SELECT kind, colour, page_path, phone FROM leads_maltipu")).all()
    assert rows == [("colour", "kremovyj", "/maltipu/kremovyj/", "+79991234567")]
    assert db.execute(text("SELECT count(*) FROM leads_buldog")).scalar() == 0
    assert db.execute(text("SELECT count(*) FROM leads_all")).scalar() == 1

    items = client.get("/api/v1/admin/leads?breed=maltipu", headers=admin_h).json()["items"]
    assert [i["kind"] for i in items] == ["colour"]
    assert client.get("/api/v1/admin/leads?breed=general", headers=admin_h).json()["total"] == 0


def test_health(client):
    assert client.get("/api/v1/health").json() == {"ok": True}
