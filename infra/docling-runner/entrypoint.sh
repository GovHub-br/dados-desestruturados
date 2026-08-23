#!/bin/sh
set -eu

PIPELINE_TMP_DIR="${PIPELINE_TMP_DIR:-/opt/pipeline-tmp}"

mkdir -p "${PIPELINE_TMP_DIR}"
chown 50000:0 "${PIPELINE_TMP_DIR}" 2>/dev/null || true
chmod 0777 "${PIPELINE_TMP_DIR}"

exec python -m docling_runtime.server
