"""Reviews get their own processing consent and the author's contact; erasure tombstones.

- consent_versions.kind: + 'review' (a separate consent for reviews: purpose, data and term differ from requests)
- reviews.phone (the author's contact — Приказ РКН № 18 wants it in the publication consent; never published),
  reviews.contact_id (erasing a person also erases their reviews); name / text nullable — cleared on withdrawal
- erasure_log.phone_hashes: keyed hashes of destroyed numbers, to destroy them again after a backup restore

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

PHONE = "phone ~ '^\\+[1-9][0-9]{7,14}$'"


def upgrade() -> None:
    op.drop_constraint(op.f("ck_consent_versions_kind"), "consent_versions", type_="check")
    op.create_check_constraint(op.f("ck_consent_versions_kind"), "consent_versions",
                               "kind IN ('processing', 'review', 'distribution', 'marketing')")
    op.add_column("erasure_log", sa.Column("phone_hashes", postgresql.JSONB(astext_type=sa.Text()),
                                           server_default=sa.text("'[]'::jsonb"), nullable=False))
    op.add_column("reviews", sa.Column("phone", sa.String(length=16), nullable=True))
    op.add_column("reviews", sa.Column("contact_id", sa.BigInteger(), nullable=True))
    op.alter_column("reviews", "name", existing_type=sa.VARCHAR(length=100), nullable=True)
    op.alter_column("reviews", "text", existing_type=sa.TEXT(), nullable=True)
    op.create_index(op.f("ix_reviews_contact_id"), "reviews", ["contact_id"], unique=False)
    op.create_foreign_key(op.f("fk_reviews_contact_id_contacts"), "reviews", "contacts", ["contact_id"], ["id"],
                          ondelete="SET NULL")
    op.create_check_constraint(op.f("ck_reviews_phone_e164"), "reviews", "phone IS NULL OR " + PHONE)
    op.create_check_constraint(op.f("ck_reviews_content_or_withdrawn"), "reviews",
                               "status = 'withdrawn' OR (name IS NOT NULL AND text IS NOT NULL)")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_reviews_content_or_withdrawn"), "reviews", type_="check")
    op.drop_constraint(op.f("ck_reviews_phone_e164"), "reviews", type_="check")
    op.drop_constraint(op.f("fk_reviews_contact_id_contacts"), "reviews", type_="foreignkey")
    op.drop_index(op.f("ix_reviews_contact_id"), table_name="reviews")
    op.execute("DELETE FROM reviews WHERE name IS NULL OR text IS NULL")
    op.alter_column("reviews", "text", existing_type=sa.TEXT(), nullable=False)
    op.alter_column("reviews", "name", existing_type=sa.VARCHAR(length=100), nullable=False)
    op.drop_column("reviews", "contact_id")
    op.drop_column("reviews", "phone")
    op.drop_column("erasure_log", "phone_hashes")
    op.execute("DELETE FROM consent_versions WHERE kind = 'review'")
    op.drop_constraint(op.f("ck_consent_versions_kind"), "consent_versions", type_="check")
    op.create_check_constraint(op.f("ck_consent_versions_kind"), "consent_versions",
                               "kind IN ('processing', 'distribution', 'marketing')")
