#!/bin/bash
# Ponto de entrada do LaunchDaemon com.ocr-cidades.docling-runner.
#
# O launchd nao executa shell de login (.zshrc, activate do venv): todo o
# ambiente do runner e montado aqui. A configuracao fica em
# $RUNNER_HOME/runner.env (modelo: runner.env.example).
set -euo pipefail

: "${RUNNER_HOME:?RUNNER_HOME deve ser definido no plist}"

set -a
# shellcheck source=/dev/null
source "$RUNNER_HOME/runner.env"
set +a

# O docling_runtime executa "python3 -m docling_pipeline" resolvendo python3
# pelo PATH. Sem o venv na frente, o subprocesso cai no Python do sistema e
# toda extracao falha, embora o /healthz continue respondendo.
export PATH="$RUNNER_HOME/venv/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONPATH="$RUNNER_HOME/repo"
export PYTHONUNBUFFERED=1

cd "$RUNNER_HOME/repo"
exec "$RUNNER_HOME/venv/bin/python" -m docling_runtime.server
