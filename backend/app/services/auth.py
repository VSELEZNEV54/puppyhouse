"""Admin authentication: login sessions (12 h absolute, 2 h idle) and service API keys (no expiry, revocable).

Brute force: failed logins are counted per login and per IP in 1-minute windows (rate_limits); above the limit the
answer is delayed and then refused for a while — never a permanent lockout, which would let anyone lock a manager out.
Unknown logins burn the same scrypt time as wrong passwords."""
from __future__ import annotations

import datetime as dt
import time

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..enums import Role
from ..errors import ApiError
from ..models import AdminToken, AdminUser, AuditLog, RateLimit
from .security import DUMMY_HASH, hash_password, new_token, rate_key, token_digest, verify_password

UTC = dt.timezone.utc


def _window() -> dt.datetime:
    return dt.datetime.now(UTC).replace(second=0, microsecond=0)


def _bump(db: Session, bucket: str) -> None:
    stmt = insert(RateLimit).values(bucket=bucket[:160], window_start=_window(), hits=1)
    db.execute(stmt.on_conflict_do_update(index_elements=[RateLimit.bucket, RateLimit.window_start],
                                          set_={"hits": RateLimit.hits + 1}))


def _failures(db: Session, bucket: str, minutes: int = 15) -> int:
    since = _window() - dt.timedelta(minutes=minutes)
    return db.scalar(select(func.coalesce(func.sum(RateLimit.hits), 0))
                     .where(RateLimit.bucket == bucket[:160], RateLimit.window_start > since)) or 0


def audit(db: Session, actor: AdminUser | None, action: str, target: str | None = None, ip: str | None = None,
          actor_label: str | None = None, **details) -> None:
    db.add(AuditLog(actor_id=actor.id if actor else None, actor_label=(actor_label or (actor.name if actor else "—"))[:100],
                    action=action, target=target, ip=ip, details=details))


def login(db: Session, login_name: str, password: str, ip: str | None) -> tuple[str, AdminUser, dt.datetime]:
    s = get_settings()
    key = login_name.strip().lower()[:100]
    ipkey = rate_key(ip) or "-"  # IPv6 grouped by /64
    pair, by_ip, by_login = f"login:{key}@{ipkey}", "login-ip:" + ipkey, "login:" + key
    # Refusal is per (login, client) and per client: failures from elsewhere never lock the real manager out.
    # Failures of this login from everywhere only slow every attempt down a little (distributed guessing).
    time.sleep(min(0.25 * (_failures(db, pair) + _failures(db, by_ip)) + 0.05 * min(_failures(db, by_login), 40),
                   3.0))
    # serialise this client's attempts: check, verify and count are atomic (parallel guesses cannot all pass)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": by_ip})
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": pair})
    if _failures(db, pair) >= s.login_per_login_15min or _failures(db, by_ip) >= s.login_per_ip_15min:
        audit(db, None, "login_blocked", target=key, ip=ip, actor_label=key)
        db.commit()
        raise ApiError(429, "rate_limited", "Слишком много попыток входа. Попробуйте через 15 минут")
    user = db.scalar(select(AdminUser).where(func.lower(AdminUser.login) == key))
    ok = verify_password(password, user.password_hash if user and user.password_hash else DUMMY_HASH)
    if not (ok and user and user.is_active and not user.is_service):
        _bump(db, pair)
        _bump(db, by_ip)
        _bump(db, by_login)
        audit(db, user, "login_failed", target=key, ip=ip, actor_label=key)
        db.commit()
        raise ApiError(401, "bad_credentials", "Неверный логин или пароль")
    token = new_token("dsh")
    now = dt.datetime.now(UTC)
    expires = now + dt.timedelta(hours=s.token_ttl_hours)
    db.add(AdminToken(token_hash=token_digest(token), kind="session", user_id=user.id, expires_at=expires,
                      last_used_at=now))
    user.last_login_at = now
    audit(db, user, "login", ip=ip)
    db.commit()
    return token, user, expires


def create_api_key(db: Session, user: AdminUser, label: str) -> str:
    token = new_token("dshk")
    db.add(AdminToken(token_hash=token_digest(token), kind="api_key", label=label[:100], user_id=user.id))
    audit(db, user, "api_key_created", target=f"user:{user.id}", label=label)
    return token


def authenticate(db: Session, token: str) -> tuple[AdminUser, AdminToken]:
    s = get_settings()
    now = dt.datetime.now(UTC)
    row = db.scalar(select(AdminToken).where(AdminToken.token_hash == token_digest(token)))
    if row is None or row.revoked_at is not None or not row.user.is_active:
        raise ApiError(401, "unauthorized", "Войдите заново")
    if row.kind == "session":
        idle_limit = (row.last_used_at or row.created_at) + dt.timedelta(hours=s.token_idle_hours)
        if (row.expires_at and row.expires_at <= now) or idle_limit <= now:
            raise ApiError(401, "session_expired", "Сессия истекла, войдите заново")
    if row.last_used_at is None or now - row.last_used_at > dt.timedelta(minutes=1):
        row.last_used_at = now  # written at most once a minute
        db.commit()
    return row.user, row


def logout(db: Session, token: AdminToken) -> None:
    token.revoked_at = dt.datetime.now(UTC)
    db.commit()


def revoke_all(db: Session, user_id: int, kinds: tuple[str, ...] = ("session", "api_key")) -> int:
    return db.execute(update(AdminToken).where(AdminToken.user_id == user_id, AdminToken.revoked_at.is_(None),
                                               AdminToken.kind.in_(kinds))
                      .values(revoked_at=func.now())).rowcount


def create_user(db: Session, login_name: str, name: str, role: Role, password: str | None,
                service: bool = False) -> AdminUser:
    s = get_settings()
    if not service and (not password or len(password) < s.min_password_len):
        raise ValueError(f"the password must be at least {s.min_password_len} characters")
    if db.scalar(select(AdminUser).where(func.lower(AdminUser.login) == login_name.strip().lower())):
        raise ValueError(f"login {login_name!r} already exists")
    user = AdminUser(login=login_name.strip(), name=name.strip(), role=role.value, is_service=service,
                     password_hash=hash_password(password) if password else None)
    db.add(user)
    db.flush()
    audit(db, None, "user_created", target=f"user:{user.id}", actor_label="CLI", role=role.value, service=service)
    return user


def set_password(db: Session, user: AdminUser, password: str) -> None:
    s = get_settings()
    if len(password) < s.min_password_len:
        raise ValueError(f"the password must be at least {s.min_password_len} characters")
    user.password_hash = hash_password(password)
    revoke_all(db, user.id, ("session",))
    audit(db, None, "password_reset", target=f"user:{user.id}", actor_label="CLI")


def purge(db: Session) -> dict:
    now = dt.datetime.now(UTC)
    return {
        "rate_limits": db.execute(delete(RateLimit).where(RateLimit.window_start < now - dt.timedelta(days=1)))
        .rowcount,
        "tokens": db.execute(delete(AdminToken).where(
            (AdminToken.kind == "session")
            & ((AdminToken.expires_at < now - dt.timedelta(days=1))
               | (AdminToken.revoked_at < now - dt.timedelta(days=1))))).rowcount,
    }
