#!/usr/bin/env bash

set -euo pipefail

project_root="${PROJECT_ROOT:-/opt/project/dados-desestruturados}"
max_attempts="${OPENMETADATA_BOOTSTRAP_MAX_ATTEMPTS:-30}"
retry_seconds="${OPENMETADATA_BOOTSTRAP_RETRY_SECONDS:-15}"

for attempt in $(seq 1 "${max_attempts}"); do
  if bash "${project_root}/infra/openmetadata/scripts/ingestar_governanca.sh"; then
    echo "Bootstrap de governança concluído."
    exit 0
  fi
  echo "Bootstrap de governança falhou (tentativa ${attempt}/${max_attempts}); nova tentativa em ${retry_seconds}s." >&2
  sleep "${retry_seconds}"
done

echo "Bootstrap de governança não concluiu após ${max_attempts} tentativas." >&2
exit 1
