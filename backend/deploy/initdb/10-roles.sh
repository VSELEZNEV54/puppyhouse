#!/bin/sh
# Runs once, when the postgres volume is created. Roles:
#   dsh_owner     — owns the schema, used only by `migrate` (DDL)
#   dsh_app       — the API and the worker: read/write data, no DDL
#   dsh_readonly  — optional, for the admin panel / BI reading the per-breed views directly
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE dsh_app LOGIN PASSWORD '${DSH_APP_DB_PASSWORD}';
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO dsh_app;
GRANT USAGE ON SCHEMA public TO dsh_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dsh_app;
ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO dsh_app;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
if [ -n "${DSH_READONLY_DB_PASSWORD:-}" ]; then
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE dsh_readonly LOGIN PASSWORD '${DSH_READONLY_DB_PASSWORD}';
GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO dsh_readonly;
GRANT USAGE ON SCHEMA public TO dsh_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE ${POSTGRES_USER} IN SCHEMA public GRANT SELECT ON TABLES TO dsh_readonly;
SQL
fi
