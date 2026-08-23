#!/usr/bin/env bash

set -euo pipefail

project_root="${PROJECT_ROOT:-/opt/project/dados-desestruturados}"
openmetadata_url="${OPENMETADATA_SERVER_URL:-http://openmetadata-server:8585/api}"
admin_email="${OPENMETADATA_ADMIN_EMAIL:-admin@open-metadata.org}"
admin_password="${OPENMETADATA_ADMIN_PASSWORD:-admin}"

export OPENMETADATA_JWT_TOKEN
OPENMETADATA_JWT_TOKEN="$({
  OPENMETADATA_SERVER_URL="${openmetadata_url}" \
  OPENMETADATA_ADMIN_EMAIL="${admin_email}" \
  OPENMETADATA_ADMIN_PASSWORD="${admin_password}" \
  python - <<'PY'
import base64
import json
import os
import urllib.request

base_url = os.environ["OPENMETADATA_SERVER_URL"].rstrip("/")
if base_url.endswith("/api"):
    base_url = base_url[:-4]
payload = json.dumps({
    "email": os.environ["OPENMETADATA_ADMIN_EMAIL"],
    "password": base64.b64encode(
        os.environ["OPENMETADATA_ADMIN_PASSWORD"].encode("utf-8")
    ).decode("ascii"),
}).encode("utf-8")
request = urllib.request.Request(
    f"{base_url}/api/v1/users/login",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(request, timeout=30) as response:
    token = json.loads(response.read().decode("utf-8"))["accessToken"]
print(token)
PY
} )"

if [[ -z "${OPENMETADATA_JWT_TOKEN}" ]]; then
  echo "Falha ao obter token do OpenMetadata." >&2
  exit 1
fi

rendered_dir="$(mktemp -d)"
trap 'rm -rf "${rendered_dir}"' EXIT

render_config() {
  local source_path="$1"
  local destination_path="$2"
  SOURCE_PATH="${source_path}" DESTINATION_PATH="${destination_path}" python - <<'PY'
import os
from pathlib import Path

content = Path(os.environ["SOURCE_PATH"]).read_text(encoding="utf-8")
for name in ("OPENMETADATA_JWT_TOKEN", "AIRFLOW_ADMIN_USER", "AIRFLOW_ADMIN_PASSWORD"):
    value = os.environ.get(name, "")
    content = content.replace("${" + name + "}", value)
Path(os.environ["DESTINATION_PATH"]).write_text(content, encoding="utf-8")
PY
}

run_ingestion() {
  local config_name="$1"
  local source_path="${project_root}/infra/openmetadata/ingestion/${config_name}"
  local rendered_path="${rendered_dir}/${config_name}"
  render_config "${source_path}" "${rendered_path}"
  echo "Ingerindo ${config_name}"
  metadata ingest -c "${rendered_path}"
}

run_ingestion "minio_ocr_cidades_storage_metadata.yaml"
run_ingestion "airflow_ocr_cidades_pipeline_metadata.yaml"
python "${project_root}/infra/openmetadata/scripts/sincronizar_linhagem_pipeline.py"

echo "Governanca OpenMetadata atualizada."
