"""Requests go to amoCRM through the outbox: outbox.channel gets 'amocrm'.

One row per request (lead.created / lead.repeat); the deal and contact ids it made are kept in leads.details["amocrm"]
(JSONB, no column needed).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-06
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_outbox_channel"), "outbox", type_="check")
    op.create_check_constraint(op.f("ck_outbox_channel"), "outbox",
                               "channel IN ('telegram', 'email', 'webhook', 'amocrm')")


def downgrade() -> None:
    op.execute("DELETE FROM outbox WHERE channel = 'amocrm'")
    op.drop_constraint(op.f("ck_outbox_channel"), "outbox", type_="check")
    op.create_check_constraint(op.f("ck_outbox_channel"), "outbox", "channel IN ('telegram', 'email', 'webhook')")
