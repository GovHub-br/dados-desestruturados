#!/usr/bin/env bash
set -euo pipefail

until pg_isready -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d "${PGDATABASE}" >/dev/null 2>&1; do
  sleep 2
done

psql -v ON_ERROR_STOP=1 -f /init.sql
