#!/usr/bin/env bash
# Set up Postgres + PostGIS directly on Debian/Ubuntu/Mint, no Docker.
#
# Docker-free alternative to `docker compose up -d`. CI still uses the
# postgis/postgis container, so parity is preserved where it matters.
#
#   ./scripts/setup_db_native.sh
#
# Idempotent — safe to re-run.

set -euo pipefail

DB_NAME=${DB_NAME:-massif}
DB_USER=${DB_USER:-massif}
DB_PASS=${DB_PASS:-massif}

echo "==> installing postgres"
sudo apt-get update -qq
sudo apt-get install -y -qq postgresql postgresql-contrib

# Whatever major version this distro shipped
PGVER=$(ls /usr/lib/postgresql | sort -n | tail -1)
echo "==> postgres $PGVER detected"

echo "==> installing postgis for $PGVER"
sudo apt-get install -y -qq "postgresql-${PGVER}-postgis-3"

echo "==> creating role and database"
sudo -u postgres psql -tAc \
  "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 || \
  sudo -u postgres psql -qc \
    "CREATE ROLE ${DB_USER} LOGIN PASSWORD '${DB_PASS}';"

sudo -u postgres psql -tAc \
  "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
  sudo -u postgres psql -qc \
    "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

# CREATE EXTENSION needs superuser. In the Docker image the app user happens to
# be superuser; here it is not, so the extensions are created up front by
# postgres and the migration's CREATE EXTENSION IF NOT EXISTS becomes a no-op.
echo "==> enabling postgis and pg_trgm"
sudo -u postgres psql -q -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS postgis;"
sudo -u postgres psql -q -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

PORT=$(sudo -u postgres psql -tAc "SHOW port;")

echo
echo "done. postgres $PGVER listening on port ${PORT}"
echo
echo "put this in your .env:"
echo
echo "DATABASE_URL=postgresql+psycopg://${DB_USER}:${DB_PASS}@localhost:${PORT}/${DB_NAME}"
echo
sudo -u postgres psql -tAc "SELECT 'postgis ' || postgis_version();" -d "${DB_NAME}"
