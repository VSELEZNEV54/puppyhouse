"""Requests follow their puppy to another breed: fk_leads_puppy_breed gets ON UPDATE CASCADE.

When src/data/puppies.json moves a puppy to another breed (a correction on the site), the catalog sync updates
puppies.breed_id; before this change the composite FK (puppy_id, breed_id) blocked that update and the whole sync
(and the deploy) failed.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-16
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("fk_leads_puppy_breed", "leads", type_="foreignkey")
    op.create_foreign_key("fk_leads_puppy_breed", "leads", "puppies", ["puppy_id", "breed_id"], ["id", "breed_id"],
                          ondelete="RESTRICT", onupdate="CASCADE")


def downgrade() -> None:
    op.drop_constraint("fk_leads_puppy_breed", "leads", type_="foreignkey")
    op.create_foreign_key("fk_leads_puppy_breed", "leads", "puppies", ["puppy_id", "breed_id"], ["id", "breed_id"],
                          ondelete="RESTRICT")
