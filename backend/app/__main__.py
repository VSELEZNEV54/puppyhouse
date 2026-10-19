"""Command line: python -m app <command>   (run from backend/, or `docker compose run --rm migrate …`)

    migrate                 drop leads_* views → alembic upgrade head → consent texts → catalog → views
    sync-catalog [--force]  breeds and puppies from src/data → DB, rebuild the per-breed views
    create-admin --login anna --name "Анна" [--role admin|manager]   (password asked, or DSH_ADMIN_PASSWORD)
    reset-password --login anna
    deactivate-admin --login anna
    create-api-key --name "Админ-панель" [--role admin|manager]     (prints the key once)
    revoke-api-keys --login <service login>
    worker                  send notifications every 10 s, purge once a night
    send-pending            send due notifications once
    notify-test             a test message to every Telegram chat and mailbox of api.env (no request needed)
    purge                   retention clean-up (see app/services/retention.py)
    forget-contact --phone +7… --reason withdrawal|request|retention|not_me --subject "ФИО"
    export-reviews [--out path]   approved reviews as JSON for the site
    reapply-erasures        after restoring a backup: destroy again everyone erased since (erasure_log hashes)
    openapi [--out path]    write the OpenAPI schema (for generating the admin panel client)
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import logging
import os
import signal
import sys
import time
import zoneinfo
from pathlib import Path

from sqlalchemy import select, text

from .config import BACKEND_DIR, get_settings
from .db import get_engine, session_scope
from .enums import Role

log = logging.getLogger("dsh.cli")
LOCK_ID = 7_310_552_014  # pg_advisory_lock key for migrations


def _alembic_cfg(connection=None):
    from alembic.config import Config
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def _wait_for_db(seconds: int = 60) -> None:
    """The database may still be starting (first boot of the container): retry the connection for a while."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception:  # noqa: BLE001
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


def _catalog_outcome(db, ok: bool, detail: str) -> None:
    from .services.auth import audit
    audit(db, None, "catalog_synced" if ok else "catalog_sync_failed", actor_label="CLI", detail=detail[:500])


def cmd_migrate(args) -> int:
    from alembic import command
    from .services import catalog, consent, views
    _wait_for_db()
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:k)"), {"k": LOCK_ID})  # one migrator at a time
            conn.commit()
            try:
                if conn.execute(text("SELECT to_regclass('leads')")).scalar():
                    views.drop_all(conn)  # a migration may change a column the views use
                conn.commit()
                command.upgrade(_alembic_cfg(conn), "head")
                conn.commit()
            finally:
                conn.rollback()
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_ID})
                conn.commit()
    except Exception:
        # The upgrade failed (PostgreSQL rolled the migration back) or the database is AHEAD of this code (an older
        # release started against a newer schema). The views were dropped above: put them back so the running API
        # keeps its breed bases, then fail the deploy. Best effort — this code's views may need columns not there.
        try:
            with session_scope() as db:
                views.rebuild(db)
        except Exception as e2:  # noqa: BLE001
            log.error("views not rebuilt after a failed upgrade: %s", e2)
        raise
    try:
        with session_scope() as db:
            print("consent:", consent.sync(db))
            if args.no_catalog:
                print("views:", views.rebuild(db))
            else:
                stats = catalog.sync(db, force=args.force)
                _catalog_outcome(db, True, f"{stats['puppies']} puppies")
                print("catalog:", stats)
    except catalog.CatalogError as e:
        # The schema is migrated; only the catalog refused (e.g. more than half of the puppies gone at once).
        # Keep the old catalog and let the API start: /api/v1/health reports it until
        # `python -m app sync-catalog --force` (or a fixed puppies.json) succeeds.
        log.error("CATALOG NOT SYNCED: %s", e)
        with session_scope() as db:
            views.rebuild(db)
            _catalog_outcome(db, False, str(e))
        print(f"CATALOG NOT SYNCED: {e}", file=sys.stderr)
        return 0 if not args.strict else 1
    except Exception:
        # any other failure: never leave the database without the views, and fail the deploy
        with session_scope() as db:
            views.rebuild(db)
        raise
    return 0


def cmd_sync_catalog(args) -> int:
    from .services import catalog, consent
    catalog.load.cache_clear()
    with session_scope() as db:
        print("consent:", consent.sync(db))
        try:
            stats = catalog.sync(db, force=args.force)
        except catalog.CatalogError as e:
            db.rollback()
            _catalog_outcome(db, False, str(e))
            db.commit()
            raise SystemExit(f"CATALOG NOT SYNCED: {e}")
        _catalog_outcome(db, True, f"{stats['puppies']} puppies")
        print("catalog:", stats)
    return 0


def _password(prompt="Пароль: ") -> str:
    pw = os.environ.get("DSH_ADMIN_PASSWORD")
    if pw:
        return pw
    a = getpass.getpass(prompt)
    b = getpass.getpass("Ещё раз: ")
    if a != b:
        raise SystemExit("пароли не совпадают")
    return a


def cmd_create_admin(args) -> int:
    from .services import auth
    with session_scope() as db:
        u = auth.create_user(db, args.login, args.name, Role(args.role), _password())
        print(f"создан {u.login} ({u.role}), id={u.id}")
    return 0


def _user(db, login):
    from sqlalchemy import func
    from .models import AdminUser
    u = db.scalar(select(AdminUser).where(func.lower(AdminUser.login) == login.lower()))
    if u is None:
        raise SystemExit(f"нет пользователя {login}")
    return u


def cmd_reset_password(args) -> int:
    from .services import auth
    with session_scope() as db:
        auth.set_password(db, _user(db, args.login), _password("Новый пароль: "))
        print("пароль изменён, все сессии закрыты")
    return 0


def cmd_deactivate_admin(args) -> int:
    from .services import auth
    with session_scope() as db:
        u = _user(db, args.login)
        u.is_active = False
        n = auth.revoke_all(db, u.id)
        auth.audit(db, None, "user_deactivated", target=f"user:{u.id}", actor_label="CLI")
        print(f"{u.login} отключён, отозвано токенов: {n}")
    return 0


def cmd_create_api_key(args) -> int:
    from .services import auth
    with session_scope() as db:
        login = "svc-" + "".join(ch for ch in args.name.lower() if ch.isalnum())[:30] + f"-{int(time.time())}"
        u = auth.create_user(db, login, args.name, Role(args.role), None, service=True)
        key = auth.create_api_key(db, u, args.name)
        print("API-ключ (показывается один раз, сохраните в секретах админ-панели):")
        print(key)
        print(f"сервисный пользователь: {u.login}")
    return 0


def cmd_revoke_api_keys(args) -> int:
    from .services import auth
    with session_scope() as db:
        u = _user(db, args.login)
        print("отозвано:", auth.revoke_all(db, u.id, ("api_key",)))
    return 0


def cmd_send_pending(args) -> int:
    from .services import notify
    with session_scope() as db:
        print(notify.deliver_due(db, limit=200))
    return 0


def cmd_notify_test(args) -> int:
    """Checks api.env as it is now (a fresh container reads it); the running API and worker take it after dsh restart."""
    from .services import notify
    res = notify.send_test()
    if not res:
        print("Уведомления не настроены: заполните DSH_TELEGRAM_BOT_TOKEN и DSH_TELEGRAM_CHAT_ID и/или DSH_SMTP_* и "
              "DSH_NOTIFY_EMAILS в /etc/domshchenkov/api.env")
        return 2
    for r in res:
        where = "Telegram" if r["channel"] == "telegram" else "почта"
        if r["ok"]:
            print(f"  ok    {where} → {r['target']}")
        else:
            print(f"  FAIL  {where} → {r['target']}: {r['hint']}" + (f"\n        ({r['error']})" if r["error"] else ""))
    if all(r["ok"] for r in res):
        print("Всё дошло. Чтобы сайт начал присылать заявки с этими настройками: dsh restart")
        return 0
    print("Исправьте /etc/domshchenkov/api.env и запустите проверку ещё раз: dsh app notify-test")
    return 1


def cmd_purge(args) -> int:
    from .services import retention
    with session_scope() as db:
        print(json.dumps(retention.run(db), ensure_ascii=False))
    return 0


def cmd_worker(args) -> int:
    """Long-running: notifications every `interval` seconds, retention purge once a night (after purge_hour)."""
    from .services import notify, retention
    s = get_settings()
    stop = {"now": False}
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))
    zone = zoneinfo.ZoneInfo(s.timezone)
    last_purge: dt.date | None = None
    log.info("worker started")
    while not stop["now"]:
        try:
            with session_scope() as db:
                st = notify.deliver_due(db, limit=50)
                if any(st.values()):
                    log.info("outbox: %s", st)
            local = dt.datetime.now(zone)
            if local.hour >= args.purge_hour and last_purge != local.date():
                with session_scope() as db:
                    log.info("purge: %s", retention.run(db))
                last_purge = local.date()
        except Exception:  # noqa: BLE001 — keep the worker alive; the error is logged
            log.exception("worker iteration failed")
        for _ in range(args.interval):
            if stop["now"]:
                break
            time.sleep(1)
    log.info("worker stopped")
    return 0


def cmd_forget_contact(args) -> int:
    from .models import Contact
    from .services import admin_people, phone as phones
    e164 = phones.normalize(args.phone)
    if not e164:
        raise SystemExit("неверный номер")
    with session_scope() as db:
        cid = find_contact(db, e164)
        if cid is None:
            raise SystemExit("нет контакта с этим номером ни в contacts, ни в contact_aliases, ни в заявках")
        res = admin_people.erase(db, cid, args.reason, args.subject, None, "CLI")
        print(json.dumps(res["counts"], ensure_ascii=False))
        for step in res["manual_steps"]:
            print("Сделайте вручную:", step)
    return 0


def find_contact(db, e164: str) -> int | None:
    """By the contact's number, an old number merged into it, or a request sent from it."""
    from .models import Contact, ContactAlias, Lead
    return (db.scalar(select(Contact.id).where(Contact.phone == e164))
            or db.scalar(select(ContactAlias.contact_id).where(ContactAlias.phone == e164))
            or db.scalar(select(Lead.contact_id).where(Lead.phone == e164, Lead.contact_id.is_not(None)).limit(1)))


def cmd_reapply_erasures(args) -> int:
    """After restoring a backup: destroy again everyone erased since (matched by keyed phone hashes)."""
    from .models import Contact, ContactAlias, ErasureLog, Review
    from .services import admin_people, security
    with session_scope() as db:
        hashes = {h for (hs,) in db.execute(select(ErasureLog.phone_hashes)) for h in (hs or [])}
        hashes |= admin_people.read_tombstones()  # erasures newer than the restored copy live only here
        phones = set(db.scalars(select(Contact.phone))) | set(db.scalars(select(ContactAlias.phone)))
        hit = [p for p in phones if security.phone_hash(p) in hashes]
        rev = [r.id for r in db.scalars(select(Review).where(Review.phone.is_not(None)))
               if security.phone_hash(r.phone) in hashes]
    done = 0
    for p in hit:
        with session_scope() as db:
            cid = find_contact(db, p)
            if cid:
                admin_people.erase(db, cid, "request", "повторное уничтожение после восстановления копии", None, "CLI")
                done += 1
    for rid in rev:
        with session_scope() as db:
            if db.get(Review, rid):
                admin_people.erase_review(db, rid, "повторное уничтожение после восстановления копии", "request",
                                          None, "CLI")
    print(f"контактов уничтожено повторно: {done}, отзывов: {len(rev)}")
    return 0


def cmd_export_reviews(args) -> int:
    from .services import admin_misc
    with session_scope() as db:
        data = admin_misc.approved_reviews(db)
    out = json.dumps({"_note": "Approved reviews exported by python -m app export-reviews", "reviews": data},
                     ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"{len(data)} отзывов → {args.out}")
    else:
        sys.stdout.write(out)
    return 0


def cmd_openapi(args) -> int:
    from .main import app
    spec = app.openapi()
    Path(args.out).write_text(json.dumps(spec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"→ {args.out}")
    return 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="python -m app", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("migrate"); p.add_argument("--force", action="store_true"); p.add_argument("--no-catalog", action="store_true")
    p.add_argument("--strict", action="store_true", help="exit 1 when the catalog refuses to sync")
    p.set_defaults(fn=cmd_migrate)
    p = sub.add_parser("sync-catalog"); p.add_argument("--force", action="store_true"); p.set_defaults(fn=cmd_sync_catalog)
    p = sub.add_parser("create-admin"); p.add_argument("--login", required=True); p.add_argument("--name", required=True)
    p.add_argument("--role", choices=[r.value for r in Role], default="manager"); p.set_defaults(fn=cmd_create_admin)
    p = sub.add_parser("reset-password"); p.add_argument("--login", required=True); p.set_defaults(fn=cmd_reset_password)
    p = sub.add_parser("deactivate-admin"); p.add_argument("--login", required=True); p.set_defaults(fn=cmd_deactivate_admin)
    p = sub.add_parser("create-api-key"); p.add_argument("--name", required=True)
    p.add_argument("--role", choices=[r.value for r in Role], default="admin"); p.set_defaults(fn=cmd_create_api_key)
    p = sub.add_parser("revoke-api-keys"); p.add_argument("--login", required=True); p.set_defaults(fn=cmd_revoke_api_keys)
    p = sub.add_parser("worker"); p.add_argument("--interval", type=int, default=10)
    p.add_argument("--purge-hour", type=int, default=3); p.set_defaults(fn=cmd_worker)
    sub.add_parser("send-pending").set_defaults(fn=cmd_send_pending)
    sub.add_parser("notify-test").set_defaults(fn=cmd_notify_test)
    sub.add_parser("purge").set_defaults(fn=cmd_purge)
    p = sub.add_parser("forget-contact"); p.add_argument("--phone", required=True)
    p.add_argument("--reason", choices=["withdrawal", "request", "retention", "not_me"], required=True)
    p.add_argument("--subject", required=True); p.set_defaults(fn=cmd_forget_contact)
    p = sub.add_parser("export-reviews"); p.add_argument("--out"); p.set_defaults(fn=cmd_export_reviews)
    sub.add_parser("reapply-erasures").set_defaults(fn=cmd_reapply_erasures)
    p = sub.add_parser("openapi"); p.add_argument("--out", default=str(BACKEND_DIR / "openapi.json"))
    p.set_defaults(fn=cmd_openapi)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
