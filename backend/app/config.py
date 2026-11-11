"""Settings from environment variables (prefix DSH_) or backend/.env. See backend/.env.example."""
from __future__ import annotations

import ipaddress
import re
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from typing import Annotated

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent
DEFAULT_DB = "postgresql+psycopg://dsh:dsh@localhost:5432/domshchenkov"

CSV = Annotated[list[str], NoDecode]  # comma-separated in the environment: DSH_CORS_ORIGINS=https://a,https://b


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DSH_", env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8",
                                      extra="ignore")

    env: str = "dev"  # dev | test | staging | prod
    database_url: str = DEFAULT_DB
    db_pool_size: int = 5
    timezone: str = "Europe/Moscow"   # stats group by this day; date filters are read in it

    # --- public API
    # Production serves the site and /api from one origin (nginx), so no CORS is needed there. The GitHub Pages
    # preview must talk to a STAGING API with its own database, never to production.
    cors_origins: CSV = Field(default_factory=list)
    admin_cors_origins: CSV = Field(default_factory=list)   # the admin panel's origin
    # Origins whose POSTs are accepted (a foreign Origin header is rejected). Empty = same host only.
    # дом-щенков.рф since 02.11.2026; домщенков.рф (the first address) stays allowed while it redirects here
    allowed_origins: CSV = Field(default_factory=lambda: [
        "https://xn----dtbefzjjef0i.xn--p1ai", "https://www.xn----dtbefzjjef0i.xn--p1ai",
        "https://xn--b1adduihee9g.xn--p1ai", "https://www.xn--b1adduihee9g.xn--p1ai"])
    # X-Real-IP is believed only from these peers (nginx). Networks allowed: 172.28.0.0/16 for the Compose network.
    trusted_proxies: CSV = Field(default_factory=lambda: ["127.0.0.1/32", "::1/128"])
    site_base_paths: CSV = Field(default_factory=lambda: ["/puppyhouse"])  # stripped from paths (GitHub Pages)
    own_hosts: CSV = Field(default_factory=lambda: ["xn----dtbefzjjef0i.xn--p1ai", "дом-щенков.рф",
                                                    "xn--b1adduihee9g.xn--p1ai", "домщенков.рф",
                                                    "dom-shchenkov.ru", "vseleznev54.github.io", "localhost"])

    # anti-spam (soft: flags; hard limits are in nginx)
    leads_per_ip_10min: int = 6       # above → flag rate_ip (the request is still saved and shown)
    leads_per_phone_hour: int = 3     # above → saved as a repeat request without a new notification
    leads_per_phone_day: int = 10
    reviews_per_ip_day: int = 3
    min_fill_ms: int = 2500           # faster → flag too_fast
    max_body_bytes: int = 16_384
    max_events_per_batch: int = 20
    repeat_window_days: int = 30      # a new request of the same person and breed joins the open lead

    # consent documents (src/data/consent.json); the current versions the forms show
    consent_file: Path = REPO_DIR / "src" / "data" / "consent.json"
    # Link page activity (pages viewed before the request) to the person. Allowed only while the processing consent
    # names this purpose — it does in consent.json. Turn off if the consent text changes.
    link_site_activity: bool = True

    # retention (days)
    keep_events_days: int = 180       # anonymous site events
    keep_ip_days: int = 30            # IP and user agent on leads and reviews (consents keep theirs)
    keep_spam_days: int = 30
    keep_contacts_days: int = 1095    # 3 years after the last request with no open lead → erased
    keep_audit_days: int = 365

    # secret for the keyed hashes of destroyed phone numbers (erasure_log.phone_hashes). Set once, keep forever
    # (and keep it outside the database backups): reapply-erasures needs the same value.
    erasure_secret: str = "dev-only-erasure-secret"
    # append-only file with the same hashes, OUTSIDE the database (and its backups): a restored older copy has an
    # older erasure_log, so reapply-erasures reads this file too. Empty = database only.
    tombstone_file: str = ""

    # admin API
    token_ttl_hours: int = 12         # absolute lifetime of a login session
    token_idle_hours: int = 2         # a session unused for this long expires
    login_per_login_15min: int = 5
    login_per_ip_15min: int = 20
    min_password_len: int = 12
    expose_docs: bool | None = None   # /api/docs; default: on everywhere except prod

    # notifications. Telegram is outside Russia: by default messages carry NO personal data (no name, no phone),
    # only the request number, breed, kind and a link to the admin panel. Setting telegram_include_pd=true is a
    # cross-border transfer and needs a notice to Роскомнадзор first (ст. 12 152-ФЗ).
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Bot API address; change only to route through your own relay (or a test stub)
    telegram_api_base: str = "https://api.telegram.org"
    # a proxy outside Russia for the Telegram calls only, when api.telegram.org is closed for the server:
    # socks5://login:password@host:port or http://login:password@host:port (11.11.2026: «Network is unreachable»)
    telegram_proxy: str = ""
    # private chats of the group's members who pressed «Старт» in the bot (notify.telegram_poll): the shared volume
    telegram_subscribers_file: str = "/var/lib/domshchenkov/telegram_subscribers.json"
    telegram_breed_chats: dict[str, str] = Field(default_factory=dict)  # {"maltipu": "-100…"} by breed key
    telegram_include_pd: bool = False
    # e-mail with full details, over SMTP of a Russian provider (Яндекс 360, VK WorkMail, Mail.ru): no transfer abroad
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_ssl: bool = True             # 465 = SSL; false → STARTTLS (587)
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    notify_emails: CSV = Field(default_factory=list)
    # false: e-mails carry only the request number, breed, kind and the admin link (like Telegram)
    email_include_pd: bool = True
    webhook_url: str = ""             # e.g. the admin panel; gets ids only, pulls the details with an API key
    webhook_secret: str = ""
    # amoCRM (a Russian service): every request from the site becomes a deal with a contact (name, phone) and a note
    # with the details; a repeat request is a note in the person's deal. On only with both the subdomain and the
    # long-lived token (amoCRM → amoМаркет → «Создать интеграцию» → «Ключи и доступы» → «Долгосрочный токен»).
    amocrm_subdomain: str = ""        # monnypassy — from https://monnypassy.amocrm.ru/ (the full address works too)
    amocrm_token: str = ""
    amocrm_pipeline_id: int | None = None          # воронка; empty → the main one (ids: `python -m app notify-check`)
    amocrm_status_id: int | None = None            # этап of that pipeline; empty → its first stage
    # true: a request lands in «Неразобранное» of the pipeline as a form request (the manager accepts or declines it);
    # DSH_AMOCRM_STATUS_ID is then not used
    amocrm_unsorted: bool = False
    amocrm_responsible_user_id: int | None = None  # empty → the user who made the token
    amocrm_tags: CSV = Field(default_factory=lambda: ["сайт"])  # on every deal, besides the breed and the kind
    # API address; empty → https://<subdomain>.amocrm.ru. Change only for a test stub
    amocrm_api_base: str = ""
    notify_max_attempts: int = 8
    admin_base_url: str = ""          # link in notifications: https://admin.example/leads/{id}
    # the deployed release (deploy.sh → docker-compose.yml): /api/v1/health shows it, so whoever pushed can see that
    # the server runs their version without a login
    release: str = ""

    # catalog
    site_data_dir: Path = REPO_DIR / "src" / "data"

    @field_validator("cors_origins", "admin_cors_origins", "allowed_origins", "trusted_proxies", "site_base_paths",
                     "own_hosts", "notify_emails", "amocrm_tags", mode="before")
    @classmethod
    def _csv(cls, v):
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()]
        return v

    @field_validator("amocrm_subdomain", mode="before")
    @classmethod
    def _amocrm_account(cls, v):
        """«https://monnypassy.amocrm.ru/leads/» → «monnypassy»; an account on another domain (amocrm.com,
        kommo.com) keeps its whole host."""
        host = re.sub(r"^[a-z]+://", "", str(v or "").strip().lower()).split("/", 1)[0].split(":", 1)[0]
        return host.removesuffix(".amocrm.ru")

    @field_validator("amocrm_token", mode="before")
    @classmethod
    def _amocrm_token(cls, v):
        return str(v or "").strip().removeprefix("Bearer ").strip()  # pasted together with «Bearer »

    @field_validator("amocrm_pipeline_id", "amocrm_status_id", "amocrm_responsible_user_id", mode="before")
    @classmethod
    def _empty_id(cls, v):
        return None if isinstance(v, str) and not v.strip() else v  # «DSH_AMOCRM_STATUS_ID=» left empty

    @field_validator("database_url")
    @classmethod
    def _psycopg3(cls, v: str) -> str:
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @model_validator(mode="after")
    def _prod_guard(self):
        for net in self.trusted_proxies:
            ipaddress.ip_network(net, strict=False)  # fail fast on a typo
        if self.env == "prod":
            problems = []
            if self.database_url == DEFAULT_DB or ":dsh@" in self.database_url:
                problems.append("DSH_DATABASE_URL uses the default password")
            if self.webhook_url and len(self.webhook_secret) < 24:
                problems.append("DSH_WEBHOOK_SECRET must be set (24+ characters) when DSH_WEBHOOK_URL is set")
            if self.erasure_secret.startswith("dev-only") or len(self.erasure_secret) < 24:
                problems.append("DSH_ERASURE_SECRET must be set (24+ random characters)")
            if not self.trusted_proxies:
                problems.append("DSH_TRUSTED_PROXIES is empty")
            if any("github.io" in o for o in self.cors_origins + self.allowed_origins):
                problems.append("the GitHub Pages preview must use a staging API, not production")
            if problems:
                raise ValueError("unsafe production settings: " + "; ".join(problems))
        return self

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"

    @property
    def amocrm_enabled(self) -> bool:
        return bool(self.amocrm_subdomain and self.amocrm_token)

    @property
    def amocrm_host(self) -> str:
        """monnypassy → monnypassy.amocrm.ru: the account's address (deal links, the default API address)."""
        sub = self.amocrm_subdomain
        return sub if "." in sub or not sub else f"{sub}.amocrm.ru"

    @property
    def docs_enabled(self) -> bool:
        return self.expose_docs if self.expose_docs is not None else not self.is_prod

    def is_trusted_proxy(self, ip: str | None) -> bool:
        if not ip:
            return False
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in ipaddress.ip_network(n, strict=False) for n in self.trusted_proxies)


@lru_cache
def get_settings() -> Settings:
    return Settings()
