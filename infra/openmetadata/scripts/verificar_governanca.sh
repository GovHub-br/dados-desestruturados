#!/usr/bin/env bash

# Verifica o catálogo governado. Não trata PDFs ou execuções como assets.
set -euo pipefail

openmetadata_url="${OPENMETADATA_SERVER_URL:-http://openmetadata-server:8585/api}"
admin_email="${OPENMETADATA_ADMIN_EMAIL:-admin@open-metadata.org}"
admin_password="${OPENMETADATA_ADMIN_PASSWORD:-admin}"

OPENMETADATA_SERVER_URL="${openmetadata_url}" \
OPENMETADATA_ADMIN_EMAIL="${admin_email}" \
OPENMETADATA_ADMIN_PASSWORD="${admin_password}" \
python - <<'PY'
import base64
import json
import os
import sys
import urllib.parse
import urllib.request

base_url = os.environ["OPENMETADATA_SERVER_URL"].rstrip("/")
if base_url.endswith("/api"):
    base_url = base_url[:-4]
payload = json.dumps({
    "email": os.environ["OPENMETADATA_ADMIN_EMAIL"],
    "password": base64.b64encode(os.environ["OPENMETADATA_ADMIN_PASSWORD"].encode()).decode(),
}).encode()
login = urllib.request.Request(
    f"{base_url}/api/v1/users/login", data=payload,
    headers={"Content-Type": "application/json"}, method="POST",
)
with urllib.request.urlopen(login, timeout=30) as response:
    token = json.loads(response.read().decode())["accessToken"]
headers = {"Authorization": f"Bearer {token}"}

def get(path):
    request = urllib.request.Request(f"{base_url}/api/v1{path}", headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())

def container(fqn):
    return get("/containers/name/" + urllib.parse.quote(fqn, safe=""))

root = "minio_ocr_cidades.ocr-cidades"
expected = {
    "documentos_origem", "contratos_semanticos", "layout_signatures",
    "extracoes_docling", "dados_resolvidos", "dados_rejeitados", "bronze",
}
containers = {}
for name in expected:
    try:
        containers[name] = container(f"{root}.{name}")
    except Exception:
        print(f"Ativo lógico MinIO ausente: {name}", file=sys.stderr)
        sys.exit(1)

all_containers = get("/containers?limit=1000").get("data", [])
forbidden = [
    item.get("name", "") for item in all_containers
    if item.get("name", "").startswith(("execucao_", "resolucao_", "fallback_"))
]
if forbidden:
    print("Foram encontrados assets operacionais indevidos: " + ", ".join(forbidden), file=sys.stderr)
    sys.exit(1)

pipeline_names = {
    item["name"] for item in get("/pipelines?service=airflow_ocr_cidades&limit=100").get("data", [])
}
expected_pipelines = {
    "dag_detecta_e_baixa_pdfs_construtoras", "dag_extrai_documentos_origem",
    "dag_resolve_schema_saida", "dag_valida_e_fallback_llm", "dag_ingere_bronze",
}
missing = expected_pipelines - pipeline_names
if missing:
    print("DAGs ausentes: " + ", ".join(sorted(missing)), file=sys.stderr)
    sys.exit(1)

lineage = get(f"/lineage/container/{containers['dados_resolvidos']['id']}?upstreamDepth=1&downstreamDepth=1")
edges = len(lineage.get("upstreamEdges", [])) + len(lineage.get("downstreamEdges", []))
if edges < 4:
    print(f"Linhagem estrutural insuficiente em dados resolvidos: {edges} arestas", file=sys.stderr)
    sys.exit(1)

print(f"Ativos lógicos estáveis: {len(expected)}")
print(f"Assets operacionais indevidos: {len(forbidden)}")
print(f"DAGs do fluxo catalogadas: {len(expected_pipelines)}")
print(f"Arestas estruturais em Dados resolvidos: {edges}")
print("Governança estável validada.")
PY
