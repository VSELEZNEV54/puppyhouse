"""Initial schema: catalog, contacts, requests (leads), history, consents, visits and events, reviews, outbox,
admin users and tokens, audit and erasure logs, login rate limits; updated_at triggers.

The per-breed views (leads_all, leads_general, leads_<breed key>) are not created here: `python -m app migrate`
drops them before and rebuilds them after every migration (app/services/views.py), so a migration can change a
column they use.

Revision ID: 0001
Revises:
Create Date: 2026-10-16
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

TOUCHED = ("leads", "contacts", "reviews")


def upgrade() -> None:
    op.create_table('admin_users',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('login', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=300), nullable=True),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('is_service', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("role IN ('admin', 'manager')", name=op.f('ck_admin_users_role')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_users'))
    )
    op.create_index('uq_admin_users_lower_login', 'admin_users', [sa.literal_column('lower(login)')], unique=True)
    op.create_table('breeds',
    sa.Column('id', sa.SmallInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('key', sa.String(length=32), nullable=False),
    sa.Column('slug', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('sort', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("key ~ '^[a-z][a-z0-9_]{0,31}$'", name=op.f('ck_breeds_key_format')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_breeds')),
    sa.UniqueConstraint('key', name=op.f('uq_breeds_key')),
    sa.UniqueConstraint('slug', name=op.f('uq_breeds_slug'))
    )
    op.create_index('uq_breeds_lower_name', 'breeds', [sa.literal_column('lower(name)')], unique=True)
    op.create_table('consent_versions',
    sa.Column('version', sa.String(length=40), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('url', sa.String(length=300), nullable=False),
    sa.Column('checkbox_text', sa.Text(), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('text_sha256', sa.String(length=64), nullable=False),
    sa.Column('effective_from', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("kind IN ('processing', 'distribution', 'marketing')", name=op.f('ck_consent_versions_kind')),
    sa.PrimaryKeyConstraint('version', name=op.f('pk_consent_versions'))
    )
    op.create_table('contacts',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('phone', sa.String(length=16), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('preferred_channel', sa.String(length=16), nullable=True),
    sa.Column('telegram_username', sa.String(length=64), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('is_blocked', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("phone ~ '^\\+[1-9][0-9]{7,14}$'", name=op.f('ck_contacts_phone_e164')),
    sa.CheckConstraint("preferred_channel IS NULL OR preferred_channel IN ('telegram', 'whatsapp', 'max', 'call')", name=op.f('ck_contacts_channel')),
    sa.CheckConstraint('char_length(name) <= 100', name=op.f('ck_contacts_name_len')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contacts')),
    sa.UniqueConstraint('phone', name=op.f('uq_contacts_phone'))
    )
    op.create_index('ix_contacts_last_seen', 'contacts', [sa.literal_column('last_seen_at DESC')], unique=False)
    op.create_table('rate_limits',
    sa.Column('bucket', sa.String(length=160), nullable=False),
    sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('hits', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('bucket', 'window_start', name=op.f('pk_rate_limits')),
    prefixes=['UNLOGGED']
    )
    op.create_table('visitors',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('first_landing', sa.String(length=300), nullable=True),
    sa.Column('first_referrer_host', sa.String(length=200), nullable=True),
    sa.Column('first_utm', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('first_source', sa.String(length=60), nullable=True),
    sa.Column('first_medium', sa.String(length=60), nullable=True),
    sa.Column('ym_uid', sa.String(length=40), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_visitors'))
    )
    op.create_table('admin_tokens',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('label', sa.String(length=100), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("kind IN ('session', 'api_key')", name=op.f('ck_admin_tokens_kind')),
    sa.CheckConstraint('char_length(token_hash) = 64', name=op.f('ck_admin_tokens_hash_len')),
    sa.ForeignKeyConstraint(['user_id'], ['admin_users.id'], name=op.f('fk_admin_tokens_user_id_admin_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_tokens')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_admin_tokens_token_hash'))
    )
    op.create_index(op.f('ix_admin_tokens_user_id'), 'admin_tokens', ['user_id'], unique=False)
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('actor_label', sa.String(length=100), nullable=False),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('target', sa.String(length=100), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['admin_users.id'], name=op.f('fk_audit_log_actor_id_admin_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    op.create_index('ix_audit_log_at', 'audit_log', ['at'], unique=False)
    op.create_table('contact_aliases',
    sa.Column('phone', sa.String(length=16), nullable=False),
    sa.Column('contact_id', sa.BigInteger(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("phone ~ '^\\+[1-9][0-9]{7,14}$'", name=op.f('ck_contact_aliases_phone_e164')),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_contact_aliases_contact_id_contacts'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('phone', name=op.f('pk_contact_aliases'))
    )
    op.create_index(op.f('ix_contact_aliases_contact_id'), 'contact_aliases', ['contact_id'], unique=False)
    op.create_table('erasure_log',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('actor_label', sa.String(length=100), nullable=False),
    sa.Column('subject', sa.String(length=200), nullable=False),
    sa.Column('reason', sa.String(length=20), nullable=False),
    sa.Column('categories', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('counts', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('method', sa.String(length=100), server_default='удаление и обезличивание записей в СУБД', nullable=False),
    sa.CheckConstraint("reason IN ('withdrawal', 'request', 'retention', 'not_me')", name=op.f('ck_erasure_log_reason')),
    sa.ForeignKeyConstraint(['actor_id'], ['admin_users.id'], name=op.f('fk_erasure_log_actor_id_admin_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_erasure_log'))
    )
    op.create_table('puppies',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('slug', sa.String(length=120), nullable=False),
    sa.Column('breed_id', sa.SmallInteger(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('sex', sa.String(length=10), nullable=True),
    sa.Column('colour', sa.String(length=60), nullable=True),
    sa.Column('generation', sa.String(length=20), nullable=True),
    sa.Column('birth_date', sa.Date(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deactivated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("sex IS NULL OR sex IN ('male', 'female')", name=op.f('ck_puppies_sex')),
    sa.CheckConstraint("status IN ('available', 'reserved', 'soon', 'sold')", name=op.f('ck_puppies_status')),
    sa.ForeignKeyConstraint(['breed_id'], ['breeds.id'], name=op.f('fk_puppies_breed_id_breeds'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_puppies')),
    sa.UniqueConstraint('id', 'breed_id', name='uq_puppies_id_breed'),
    sa.UniqueConstraint('slug', name=op.f('uq_puppies_slug'))
    )
    op.create_index(op.f('ix_puppies_breed_id'), 'puppies', ['breed_id'], unique=False)
    op.create_table('reviews',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('display_name', sa.String(length=60), nullable=False),
    sa.Column('city', sa.String(length=100), nullable=True),
    sa.Column('breed_id', sa.SmallInteger(), nullable=True),
    sa.Column('rating', sa.SmallInteger(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('moderated_by', sa.Integer(), nullable=True),
    sa.Column('moderated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('moderator_note', sa.String(length=300), nullable=True),
    sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('page_path', sa.String(length=300), nullable=True),
    sa.Column('visitor_id', sa.UUID(), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.String(length=400), nullable=True),
    sa.Column('idempotency_key', sa.UUID(), nullable=False),
    sa.Column('request_sha256', sa.String(length=64), nullable=True),
    sa.Column('spam_reason', sa.String(length=20), nullable=True),
    sa.CheckConstraint("spam_reason IS NULL OR spam_reason IN ('honeypot', 'too_fast', 'rate_limited', 'blocked_contact', 'manual')", name=op.f('ck_reviews_spam_reason')),
    sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'withdrawn')", name=op.f('ck_reviews_status')),
    sa.CheckConstraint('char_length(text) <= 4000', name=op.f('ck_reviews_text_len')),
    sa.CheckConstraint('rating BETWEEN 1 AND 5', name=op.f('ck_reviews_rating')),
    sa.ForeignKeyConstraint(['breed_id'], ['breeds.id'], name=op.f('fk_reviews_breed_id_breeds'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['moderated_by'], ['admin_users.id'], name=op.f('fk_reviews_moderated_by_admin_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reviews')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_reviews_idempotency_key'))
    )
    op.create_index('ix_reviews_ip_created', 'reviews', ['ip', 'created_at'], unique=False)
    op.create_index('ix_reviews_status_created', 'reviews', ['status', sa.literal_column('created_at DESC')], unique=False)
    op.create_table('sessions',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('visitor_id', sa.UUID(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('landing_path', sa.String(length=300), nullable=True),
    sa.Column('referrer_host', sa.String(length=200), nullable=True),
    sa.Column('utm', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('source', sa.String(length=60), nullable=True),
    sa.Column('medium', sa.String(length=60), nullable=True),
    sa.Column('device', sa.String(length=10), nullable=True),
    sa.Column('events_count', sa.Integer(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], name=op.f('fk_sessions_visitor_id_visitors'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sessions'))
    )
    op.create_index('ix_sessions_started', 'sessions', ['started_at'], unique=False)
    op.create_index('ix_sessions_visitor_started', 'sessions', ['visitor_id', 'started_at'], unique=False)
    op.create_table('leads',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('public_id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('origin', sa.String(length=16), server_default='site_form', nullable=False),
    sa.Column('parent_id', sa.BigInteger(), nullable=True),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('breed_id', sa.SmallInteger(), nullable=True),
    sa.Column('breed_input', sa.String(length=100), nullable=True),
    sa.Column('puppy_id', sa.Integer(), nullable=True),
    sa.Column('puppy_slug', sa.String(length=120), nullable=True),
    sa.Column('puppy_name', sa.String(length=100), nullable=True),
    sa.Column('colour', sa.String(length=40), nullable=True),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('form_title', sa.String(length=200), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('contact_id', sa.BigInteger(), nullable=True),
    sa.Column('name', sa.String(length=100), nullable=True),
    sa.Column('phone', sa.String(length=16), nullable=True),
    sa.Column('anonymised_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('is_repeat', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('page_path', sa.String(length=300), nullable=True),
    sa.Column('page_title', sa.String(length=200), nullable=True),
    sa.Column('referrer_host', sa.String(length=200), nullable=True),
    sa.Column('landing_path', sa.String(length=300), nullable=True),
    sa.Column('utm', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('source', sa.String(length=60), nullable=True),
    sa.Column('medium', sa.String(length=60), nullable=True),
    sa.Column('visitor_id', sa.UUID(), nullable=True),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('consent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('consent_version', sa.String(length=40), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.String(length=400), nullable=True),
    sa.Column('idempotency_key', sa.UUID(), nullable=True),
    sa.Column('request_sha256', sa.String(length=64), nullable=True),
    sa.Column('spam_reason', sa.String(length=20), nullable=True),
    sa.Column('flags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
    sa.Column('status', sa.String(length=16), server_default='new', nullable=False),
    sa.Column('status_changed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_activity_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('first_response_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_contact_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('lost_reason', sa.String(length=20), nullable=True),
    sa.Column('sale_amount', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('assignee_id', sa.Integer(), nullable=True),
    sa.CheckConstraint("channel IN ('telegram', 'whatsapp', 'max', 'call')", name=op.f('ck_leads_channel')),
    sa.CheckConstraint("colour IS NULL OR colour ~ '^[a-z][a-z-]{0,39}$'", name=op.f('ck_leads_colour_slug')),
    sa.CheckConstraint("jsonb_typeof(details) = 'object'", name=op.f('ck_leads_details_object')),
    sa.CheckConstraint("jsonb_typeof(flags) = 'array'", name=op.f('ck_leads_flags_array')),
    sa.CheckConstraint("kind IN ('lead', 'price', 'puppy', 'consult', 'colour', 'help', 'waitlist', 'video_call', 'litter', 'shop', 'other')", name=op.f('ck_leads_kind')),
    sa.CheckConstraint("lost_reason IS NULL OR lost_reason IN ('expensive', 'bought_elsewhere', 'no_response', 'changed_mind', 'no_match', 'other')", name=op.f('ck_leads_lost_reason')),
    sa.CheckConstraint("origin <> 'site_form' OR (consent_at IS NOT NULL AND consent_version IS NOT NULL)", name=op.f('ck_leads_site_form_consent')),
    sa.CheckConstraint("origin IN ('site_form', 'phone', 'telegram', 'whatsapp', 'max', 'avito', 'instagram', 'referral', 'other')", name=op.f('ck_leads_origin')),
    sa.CheckConstraint("phone IS NULL OR phone ~ '^\\+[1-9][0-9]{7,14}$'", name=op.f('ck_leads_phone_e164')),
    sa.CheckConstraint("spam_reason IS NULL OR spam_reason IN ('honeypot', 'too_fast', 'rate_limited', 'blocked_contact', 'manual')", name=op.f('ck_leads_spam_reason')),
    sa.CheckConstraint("status IN ('new', 'no_answer', 'in_progress', 'waitlist', 'reserved', 'won', 'lost', 'duplicate', 'spam')", name=op.f('ck_leads_status')),
    sa.CheckConstraint('anonymised_at IS NOT NULL OR (contact_id IS NOT NULL AND name IS NOT NULL AND phone IS NOT NULL)', name=op.f('ck_leads_person_or_anonymised')),
    sa.CheckConstraint('parent_id IS NULL OR parent_id <> id', name=op.f('ck_leads_parent_not_self')),
    sa.CheckConstraint('puppy_id IS NULL OR breed_id IS NOT NULL', name=op.f('ck_leads_puppy_needs_breed')),
    sa.CheckConstraint('sale_amount IS NULL OR sale_amount >= 0', name=op.f('ck_leads_sale_amount')),
    sa.ForeignKeyConstraint(['assignee_id'], ['admin_users.id'], name=op.f('fk_leads_assignee_id_admin_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['breed_id'], ['breeds.id'], name=op.f('fk_leads_breed_id_breeds'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['consent_version'], ['consent_versions.version'], name=op.f('fk_leads_consent_version_consent_versions'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_leads_contact_id_contacts'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['parent_id'], ['leads.id'], name=op.f('fk_leads_parent_id_leads'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['puppy_id', 'breed_id'], ['puppies.id', 'puppies.breed_id'], name='fk_leads_puppy_breed', ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leads')),
    sa.UniqueConstraint('idempotency_key', name=op.f('uq_leads_idempotency_key')),
    sa.UniqueConstraint('public_id', name=op.f('uq_leads_public_id'))
    )
    op.create_index('ix_leads_assignee_status', 'leads', ['assignee_id', 'status'], unique=False, postgresql_where=sa.text('assignee_id IS NOT NULL'))
    op.create_index('ix_leads_breed_created', 'leads', ['breed_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('ix_leads_contact_created', 'leads', ['contact_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('ix_leads_created', 'leads', [sa.literal_column('created_at DESC'), sa.literal_column('id DESC')], unique=False)
    op.create_index('ix_leads_ip_created', 'leads', ['ip', 'created_at'], unique=False)
    op.create_index('ix_leads_next_contact', 'leads', ['next_contact_at'], unique=False, postgresql_where=sa.text('next_contact_at IS NOT NULL'))
    op.create_index('ix_leads_parent', 'leads', ['parent_id'], unique=False, postgresql_where=sa.text('parent_id IS NOT NULL'))
    op.create_index('ix_leads_puppy', 'leads', ['puppy_id'], unique=False, postgresql_where=sa.text('puppy_id IS NOT NULL'))
    op.create_index('ix_leads_status_created', 'leads', ['status', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('ix_leads_visitor', 'leads', ['visitor_id'], unique=False, postgresql_where=sa.text('visitor_id IS NOT NULL'))
    op.create_table('site_events',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('visitor_id', sa.UUID(), nullable=False),
    sa.Column('session_id', sa.UUID(), nullable=True),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('path', sa.String(length=300), nullable=True),
    sa.Column('breed_key', sa.String(length=32), nullable=True),
    sa.Column('puppy_slug', sa.String(length=120), nullable=True),
    sa.Column('data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("jsonb_typeof(data) = 'object'", name=op.f('ck_site_events_data_object')),
    sa.CheckConstraint("type ~ '^[a-z_]{1,32}$'", name=op.f('ck_site_events_type_format')),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_site_events_session_id_sessions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['visitor_id'], ['visitors.id'], name=op.f('fk_site_events_visitor_id_visitors'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_site_events'))
    )
    op.create_index('ix_site_events_received', 'site_events', ['received_at'], unique=False)
    op.create_index('ix_site_events_session', 'site_events', ['session_id'], unique=False)
    op.create_index('ix_site_events_type_received', 'site_events', ['type', 'received_at'], unique=False)
    op.create_index('ix_site_events_visitor_occurred', 'site_events', ['visitor_id', 'occurred_at'], unique=False)
    op.create_table('consents',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('given_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('version', sa.String(length=40), nullable=False),
    sa.Column('contact_id', sa.BigInteger(), nullable=True),
    sa.Column('lead_id', sa.BigInteger(), nullable=True),
    sa.Column('review_id', sa.BigInteger(), nullable=True),
    sa.Column('page_path', sa.String(length=300), nullable=True),
    sa.Column('ip', postgresql.INET(), nullable=True),
    sa.Column('user_agent', sa.String(length=400), nullable=True),
    sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('num_nonnulls(contact_id, review_id) >= 1', name=op.f('ck_consents_has_subject')),
    sa.ForeignKeyConstraint(['contact_id'], ['contacts.id'], name=op.f('fk_consents_contact_id_contacts'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], name=op.f('fk_consents_lead_id_leads'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], name=op.f('fk_consents_review_id_reviews'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['version'], ['consent_versions.version'], name=op.f('fk_consents_version_consent_versions'), ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_consents'))
    )
    op.create_index(op.f('ix_consents_contact_id'), 'consents', ['contact_id'], unique=False)
    op.create_index(op.f('ix_consents_lead_id'), 'consents', ['lead_id'], unique=False)
    op.create_index(op.f('ix_consents_review_id'), 'consents', ['review_id'], unique=False)
    op.create_table('lead_history',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('lead_id', sa.BigInteger(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=True),
    sa.Column('actor_label', sa.String(length=100), nullable=False),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('old_value', sa.String(length=300), nullable=True),
    sa.Column('new_value', sa.String(length=300), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.CheckConstraint("action IN ('created', 'repeat', 'status', 'assignee', 'breed', 'puppy', 'next_contact', 'comment', 'edit', 'merged')", name=op.f('ck_lead_history_action')),
    sa.ForeignKeyConstraint(['actor_id'], ['admin_users.id'], name=op.f('fk_lead_history_actor_id_admin_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], name=op.f('fk_lead_history_lead_id_leads'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lead_history'))
    )
    op.create_index('ix_lead_history_lead_at', 'lead_history', ['lead_id', 'at'], unique=False)
    op.create_table('outbox',
    sa.Column('id', sa.BigInteger(), sa.Identity(always=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('channel', sa.String(length=16), nullable=False),
    sa.Column('target', sa.String(length=300), nullable=False),
    sa.Column('event', sa.String(length=32), nullable=False),
    sa.Column('lead_id', sa.BigInteger(), nullable=True),
    sa.Column('review_id', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
    sa.Column('attempts', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_error', sa.String(length=500), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("channel IN ('telegram', 'email', 'webhook')", name=op.f('ck_outbox_channel')),
    sa.CheckConstraint("status IN ('pending', 'sent', 'failed')", name=op.f('ck_outbox_status')),
    sa.CheckConstraint('attempts >= 0', name=op.f('ck_outbox_attempts')),
    sa.CheckConstraint('num_nonnulls(lead_id, review_id) = 1', name=op.f('ck_outbox_one_subject')),
    sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], name=op.f('fk_outbox_lead_id_leads'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], name=op.f('fk_outbox_review_id_reviews'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_outbox'))
    )
    op.create_index('ix_outbox_due', 'outbox', ['next_attempt_at'], unique=False, postgresql_where=sa.text("status = 'pending'"))
    op.create_index(op.f('ix_outbox_lead_id'), 'outbox', ['lead_id'], unique=False)
    op.create_index(op.f('ix_outbox_review_id'), 'outbox', ['review_id'], unique=False)
    op.create_index('uq_outbox_lead_created', 'outbox', ['lead_id', 'channel', 'target'], unique=True, postgresql_where=sa.text("event = 'lead.created'"))
    op.create_index('uq_outbox_review_created', 'outbox', ['review_id', 'channel', 'target'], unique=True, postgresql_where=sa.text("event = 'review.created'"))

    # updated_at is kept by the database itself: raw SQL fixes and bulk updates cannot forget it
    op.execute("""
        CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at := now();
            RETURN NEW;
        END $$;
    """)
    for table in TOUCHED:
        op.execute(f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
                   f"FOR EACH ROW EXECUTE FUNCTION set_updated_at()")


def downgrade() -> None:
    for table in TOUCHED:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.drop_index('uq_outbox_review_created', table_name='outbox', postgresql_where=sa.text("event = 'review.created'"))
    op.drop_index('uq_outbox_lead_created', table_name='outbox', postgresql_where=sa.text("event = 'lead.created'"))
    op.drop_index(op.f('ix_outbox_review_id'), table_name='outbox')
    op.drop_index(op.f('ix_outbox_lead_id'), table_name='outbox')
    op.drop_index('ix_outbox_due', table_name='outbox', postgresql_where=sa.text("status = 'pending'"))
    op.drop_table('outbox')
    op.drop_index('ix_lead_history_lead_at', table_name='lead_history')
    op.drop_table('lead_history')
    op.drop_index(op.f('ix_consents_review_id'), table_name='consents')
    op.drop_index(op.f('ix_consents_lead_id'), table_name='consents')
    op.drop_index(op.f('ix_consents_contact_id'), table_name='consents')
    op.drop_table('consents')
    op.drop_index('ix_site_events_visitor_occurred', table_name='site_events')
    op.drop_index('ix_site_events_type_received', table_name='site_events')
    op.drop_index('ix_site_events_session', table_name='site_events')
    op.drop_index('ix_site_events_received', table_name='site_events')
    op.drop_table('site_events')
    op.drop_index('ix_leads_visitor', table_name='leads', postgresql_where=sa.text('visitor_id IS NOT NULL'))
    op.drop_index('ix_leads_status_created', table_name='leads')
    op.drop_index('ix_leads_puppy', table_name='leads', postgresql_where=sa.text('puppy_id IS NOT NULL'))
    op.drop_index('ix_leads_parent', table_name='leads', postgresql_where=sa.text('parent_id IS NOT NULL'))
    op.drop_index('ix_leads_next_contact', table_name='leads', postgresql_where=sa.text('next_contact_at IS NOT NULL'))
    op.drop_index('ix_leads_ip_created', table_name='leads')
    op.drop_index('ix_leads_created', table_name='leads')
    op.drop_index('ix_leads_contact_created', table_name='leads')
    op.drop_index('ix_leads_breed_created', table_name='leads')
    op.drop_index('ix_leads_assignee_status', table_name='leads', postgresql_where=sa.text('assignee_id IS NOT NULL'))
    op.drop_table('leads')
    op.drop_index('ix_sessions_visitor_started', table_name='sessions')
    op.drop_index('ix_sessions_started', table_name='sessions')
    op.drop_table('sessions')
    op.drop_index('ix_reviews_status_created', table_name='reviews')
    op.drop_index('ix_reviews_ip_created', table_name='reviews')
    op.drop_table('reviews')
    op.drop_index(op.f('ix_puppies_breed_id'), table_name='puppies')
    op.drop_table('puppies')
    op.drop_table('erasure_log')
    op.drop_index(op.f('ix_contact_aliases_contact_id'), table_name='contact_aliases')
    op.drop_table('contact_aliases')
    op.drop_index('ix_audit_log_at', table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_index(op.f('ix_admin_tokens_user_id'), table_name='admin_tokens')
    op.drop_table('admin_tokens')
    op.drop_table('visitors')
    op.drop_table('rate_limits')
    op.drop_index('ix_contacts_last_seen', table_name='contacts')
    op.drop_table('contacts')
    op.drop_table('consent_versions')
    op.drop_index('uq_breeds_lower_name', table_name='breeds')
    op.drop_table('breeds')
    op.drop_index('uq_admin_users_lower_login', table_name='admin_users')
    op.drop_table('admin_users')
