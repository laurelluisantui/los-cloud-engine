#!/bin/sh
set -eu

# The API/worker must NOT connect as the container's postgres superuser:
# superusers bypass RLS even when FORCE ROW LEVEL SECURITY is enabled.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v app_password="$ENGINE_DB_PASSWORD" <<'SQL'
CREATE ROLE los_app LOGIN PASSWORD :'app_password';
ALTER DATABASE engine OWNER TO los_app;
SQL
