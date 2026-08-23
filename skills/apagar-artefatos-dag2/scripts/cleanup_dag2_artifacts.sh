#!/usr/bin/env bash
set -euo pipefail

MINIO_CONTAINER="${MINIO_CONTAINER:-ocr_minio}"
MINIO_ALIAS="${MINIO_ALIAS:-local}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin123}"
MINIO_BUCKET_DATA_LAKE="${MINIO_BUCKET_DATA_LAKE:-ocr-cidades}"
MINIO_RESOLUTION_PREFIX="${MINIO_RESOLUTION_PREFIX:-execucoes/construtoras/resolucao}"

MODE="dry-run"
EXECUTION_PREFIX=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      MODE="dry-run"
      shift
      ;;
    --apply)
      MODE="apply"
      shift
      ;;
    --execution-prefix)
      [[ $# -ge 2 ]] || { echo "--execution-prefix exige um valor" >&2; exit 2; }
      EXECUTION_PREFIX="$2"
      shift 2
      ;;
    *)
      echo "Argumento desconhecido: $1" >&2
      exit 2
      ;;
  esac
done

if [[ "$MINIO_RESOLUTION_PREFIX" != "execucoes/construtoras/resolucao" ]]; then
  echo "Prefixo recusado por seguranca: $MINIO_RESOLUTION_PREFIX" >&2
  exit 3
fi

EXECUTION_PREFIX="${EXECUTION_PREFIX#/}"
EXECUTION_PREFIX="${EXECUTION_PREFIX%/}"
if [[ "$EXECUTION_PREFIX" == *".."* ]]; then
  echo "execution-prefix invalido" >&2
  exit 3
fi

TARGET="$MINIO_ALIAS/$MINIO_BUCKET_DATA_LAKE/$MINIO_RESOLUTION_PREFIX"
if [[ -n "$EXECUTION_PREFIX" ]]; then
  TARGET="$TARGET/$EXECUTION_PREFIX"
fi
TARGET="${TARGET%/}/"

docker exec "$MINIO_CONTAINER" mc alias set \
  "$MINIO_ALIAS" "$MINIO_ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null

echo "Escopo protegido: $TARGET"
docker exec "$MINIO_CONTAINER" mc ls --recursive "$TARGET" || true

if [[ "$MODE" == "dry-run" ]]; then
  echo "Dry-run concluido. Nenhum objeto foi removido."
  exit 0
fi

docker exec "$MINIO_CONTAINER" mc rm --recursive --force "$TARGET"
echo "Remocao concluida somente em: $TARGET"
