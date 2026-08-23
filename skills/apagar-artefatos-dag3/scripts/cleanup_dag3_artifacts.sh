#!/usr/bin/env bash
set -euo pipefail

MINIO_CONTAINER="${MINIO_CONTAINER:-ocr_minio}"
MINIO_ALIAS="${MINIO_ALIAS:-local}"
MINIO_ENDPOINT="${MINIO_ENDPOINT:-http://localhost:9000}"
MINIO_ROOT_USER="${MINIO_ROOT_USER:-minioadmin}"
MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD:-minioadmin123}"
MINIO_BUCKET_DATA_LAKE="${MINIO_BUCKET_DATA_LAKE:-ocr-cidades}"
MINIO_FALLBACK_PREFIX="${MINIO_FALLBACK_PREFIX:-fallback/construtoras}"
MINIO_LAYOUT_PREFIX="${MINIO_LAYOUT_PREFIX:-layouts/construtoras}"

MODE="dry-run"
EXECUTION_PREFIX=""
INCLUDE_LAYOUTS="false"

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
    --include-published-layouts)
      INCLUDE_LAYOUTS="true"
      shift
      ;;
    *)
      echo "Argumento desconhecido: $1" >&2
      exit 2
      ;;
  esac
done

if [[ "$MINIO_FALLBACK_PREFIX" != "fallback/construtoras" ]]; then
  echo "Prefixo de fallback recusado por seguranca: $MINIO_FALLBACK_PREFIX" >&2
  exit 3
fi
if [[ "$MINIO_LAYOUT_PREFIX" != "layouts/construtoras" ]]; then
  echo "Prefixo de layouts recusado por seguranca: $MINIO_LAYOUT_PREFIX" >&2
  exit 3
fi

EXECUTION_PREFIX="${EXECUTION_PREFIX#/}"
EXECUTION_PREFIX="${EXECUTION_PREFIX%/}"
if [[ "$EXECUTION_PREFIX" == *".."* ]]; then
  echo "execution-prefix invalido" >&2
  exit 3
fi
if [[ "$INCLUDE_LAYOUTS" == "true" && -n "$EXECUTION_PREFIX" ]]; then
  echo "Nao combine --execution-prefix com --include-published-layouts" >&2
  exit 3
fi

docker inspect -f '{{.State.Running}}' "$MINIO_CONTAINER" 2>/dev/null | grep -qx true || {
  echo "Container MinIO nao esta ativo: $MINIO_CONTAINER" >&2
  exit 4
}

docker exec "$MINIO_CONTAINER" mc alias set \
  "$MINIO_ALIAS" "$MINIO_ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null

FALLBACK_TARGET="$MINIO_ALIAS/$MINIO_BUCKET_DATA_LAKE/$MINIO_FALLBACK_PREFIX"
if [[ -n "$EXECUTION_PREFIX" ]]; then
  FALLBACK_TARGET="$FALLBACK_TARGET/$EXECUTION_PREFIX"
fi
FALLBACK_TARGET="${FALLBACK_TARGET%/}/"

TARGETS=("$FALLBACK_TARGET")
if [[ "$INCLUDE_LAYOUTS" == "true" ]]; then
  TARGETS+=("$MINIO_ALIAS/$MINIO_BUCKET_DATA_LAKE/$MINIO_LAYOUT_PREFIX/")
fi

for target in "${TARGETS[@]}"; do
  echo "Escopo protegido: $target"
  docker exec "$MINIO_CONTAINER" mc ls --recursive "$target" || true
done

if [[ "$MODE" == "dry-run" ]]; then
  echo "Dry-run concluido. Nenhum objeto foi removido."
  exit 0
fi

for target in "${TARGETS[@]}"; do
  docker exec "$MINIO_CONTAINER" mc rm --recursive --force "$target"
  echo "Remocao concluida somente em: $target"
done
