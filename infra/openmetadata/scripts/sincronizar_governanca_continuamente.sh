#!/usr/bin/env bash

set -euo pipefail

project_root="${PROJECT_ROOT:-/opt/project/dados-desestruturados}"
interval_seconds="${OPENMETADATA_CATALOG_SYNC_INTERVAL_SECONDS:-300}"

if (( interval_seconds < 60 )); then
  interval_seconds=60
fi

while true; do
  if ! bash "${project_root}/infra/openmetadata/scripts/ingestar_governanca.sh"; then
    echo "Sincronização de governança falhou; será tentada novamente no próximo ciclo." >&2
  fi
  sleep "${interval_seconds}"
done
