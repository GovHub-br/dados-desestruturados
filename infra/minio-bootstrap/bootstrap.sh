#!/bin/sh

set -eu

bucket="${MINIO_BUCKET_DATA_LAKE:-ocr-cidades}"
contract_source="/bootstrap/contracts/construtoras/v1.8.0/contrato_semantico_construtora.json"
contract_key="contratos/construtoras/v1.8.0/contrato_semantico_construtora.json"

mc alias set local \
  "http://minio:9000" \
  "${MINIO_ROOT_USER:-minioadmin}" \
  "${MINIO_ROOT_PASSWORD:-minioadmin123}"

mc mb --ignore-existing "local/${bucket}"
mc anonymous set private "local/${bucket}"

# O bootstrap apenas publica a versao inicial. Uma versao ja existente no MinIO
# e preservada para evitar sobrescrever contratos publicados manualmente.
if ! mc stat "local/${bucket}/${contract_key}" >/dev/null 2>&1; then
  mc cp "${contract_source}" "local/${bucket}/${contract_key}"
  echo "Contrato semantico bootstrapado: ${contract_key}"
else
  echo "Contrato semantico ja existe; bootstrap ignorado: ${contract_key}"
fi
