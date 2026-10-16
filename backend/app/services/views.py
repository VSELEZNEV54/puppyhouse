"""Per-breed «bases» as SQL views with readable columns, for direct SQL / BI / the admin panel's own database tools.

    leads_all       — every request, with the breed name (the «one big base»)
    leads_<key>     — one per breed: leads_maltipu, leads_buldog, leads_pudel, leads_kolli
    leads_general   — requests without a breed («Пока не решил(а)»)

Views have an explicit column list, so they never freeze a `SELECT *`. They are dropped before migrations
(a migration may alter a column a view uses) and rebuilt after migrations and after every catalog sync."""
from __future__ import annotations

import re

from sqlalchemy import Connection, select, text
from sqlalchemy.orm import Session

from ..models import Breed

_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")

COLUMNS = """
    l.id                                   AS lead_id,
    l.created_at                           AS created_at,
    l.status                               AS status,
    l.kind                                 AS kind,
    l.origin                               AS origin,
    l.parent_id                            AS parent_id,
    b.key                                  AS breed_key,
    b.name                                 AS breed,
    l.breed_input                          AS breed_input,
    COALESCE(p.slug, l.puppy_slug)         AS puppy_slug,
    COALESCE(l.puppy_name, p.name)         AS puppy_name,
    l.colour                               AS colour,
    l.note                                 AS note,
    l.name                                 AS name,
    l.phone                                AS phone,
    l.channel                              AS reply_channel,
    l.contact_id                           AS contact_id,
    l.is_repeat                            AS is_repeat,
    a.name                                 AS assignee,
    l.next_contact_at                      AS next_contact_at,
    l.first_response_at                    AS first_response_at,
    l.closed_at                            AS closed_at,
    l.lost_reason                          AS lost_reason,
    l.sale_amount                          AS sale_amount,
    l.page_path                            AS page_path,
    l.source                               AS source,
    l.medium                               AS medium,
    l.utm ->> 'campaign'                   AS utm_campaign,
    l.spam_reason                          AS spam_reason,
    l.updated_at                           AS updated_at
FROM leads l
LEFT JOIN breeds b ON b.id = l.breed_id
LEFT JOIN puppies p ON p.id = l.puppy_id
LEFT JOIN admin_users a ON a.id = l.assignee_id"""


def view_name(key: str) -> str:
    if not _KEY.fullmatch(key) or key in ("all", "general"):
        raise ValueError(f"bad breed key {key!r}")
    return f"leads_{key}"


def _exec(conn: Connection | Session, sql: str) -> None:
    conn.execute(text(sql))


def drop_all(conn: Connection | Session) -> None:
    rows = conn.execute(text("SELECT viewname FROM pg_views WHERE schemaname = current_schema() "
                             "AND viewname LIKE 'leads\\_%'")).all()
    for (name,) in rows:
        if re.fullmatch(r"leads_[a-z0-9_]+", name):
            _exec(conn, f'DROP VIEW IF EXISTS "{name}"')


def rebuild(conn: Connection | Session) -> list[str]:
    """Drop and recreate every leads_* view. Idempotent; runs inside the caller's transaction."""
    drop_all(conn)
    names = ["leads_all", "leads_general"]
    _exec(conn, f"CREATE VIEW leads_all AS SELECT {COLUMNS}")
    _exec(conn, f"CREATE VIEW leads_general AS SELECT {COLUMNS}\nWHERE l.breed_id IS NULL")
    keys = conn.execute(select(Breed.key).order_by(Breed.sort, Breed.id)).scalars().all()
    for key in keys:
        name = view_name(key)  # validated: safe to put into SQL
        _exec(conn, f"CREATE VIEW {name} AS SELECT {COLUMNS}\n"
                    f"WHERE l.breed_id = (SELECT id FROM breeds WHERE key = '{key}')")
        names.append(name)
    # the optional read-only role (BI, the panel's own database tools) sees these views and nothing else
    conn.execute(text(
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dsh_readonly') THEN "
        + " ".join(f"GRANT SELECT ON {n} TO dsh_readonly;" for n in names) + " END IF; END $$"))
    return names
