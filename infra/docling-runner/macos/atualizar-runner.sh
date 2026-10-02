#!/bin/bash
# Atualiza o runner Docling do Mac Studio para a versao mais nova de um branch.
#
# Uso: atualizar-runner.sh [branch]   (padrao: o branch em uso no clone, normalmente main)
#
# Roda sozinho a cada 15 min pelo LaunchDaemon
# com.ocr-cidades.docling-runner-atualizacao, e tambem pode ser executado a mao.
# Sem argumento, acompanha o branch em uso: para testar um branch, rode com o
# nome dele; para voltar, rode com "main".
#
#   1. busca o branch e sai se nao houver commit novo (ou se ele ja falhou antes);
#   2. espera nao haver extracao em andamento;
#   3. troca o codigo do clone dedicado;
#   4. reinstala dependencias se requirements.txt ou os patches mudaram;
#   5. valida o pipeline no mesmo ambiente do servico;
#   6. reinicia o runner (o launchd religa) e espera o /healthz.
# Se 4, 5 ou 6 falharem, volta ao commit anterior e termina com erro.
#
# Detalhes: docs/operations/docling-runner-launchd.md
set -euo pipefail

RUNNER_HOME="${RUNNER_HOME:-$HOME/docling-runner}"
REPO="$RUNNER_HOME/repo"
VENV="$RUNNER_HOME/venv"
SERVICO="system/com.ocr-cidades.docling-runner"
HEALTHZ="http://127.0.0.1:8081/healthz"
PATCHES="infra/airflow/scripts/apply_docling_vlm_patches.py"
LOCK="$RUNNER_HOME/.atualizacao.lock"
HISTORICO="$RUNNER_HOME/atualizacoes.log"
# Ultimo commit revertido: nao e tentado de novo a cada execucao agendada.
COMMIT_COM_FALHA="$RUNNER_HOME/.commit-com-falha"
# Os colchetes impedem que o padrao case com o proprio pgrep/pkill.
PROC_SERVIDOR='[-]m docling_runtime[.]server'
PROC_EXTRACAO='[-]m docling_pipeline'

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
falhar() { log "ERRO: $*" >&2; exit 1; }

# A trava guarda o PID do dono. Se a execucao anterior foi interrompida (reboot,
# kill), a trava fica orfa e e removida aqui; sem isso, a atualizacao
# automatica pararia para sempre.
adquirir_trava() {
  local dono
  if ! mkdir "$LOCK" 2>/dev/null; then
    dono="$(cat "$LOCK/pid" 2>/dev/null || true)"
    if [ -n "$dono" ] && ps -p "$dono" -o command= 2>/dev/null | grep -q 'atualizar-runner'; then
      falhar "outra atualizacao em andamento (pid $dono)"
    fi
    log "Removendo trava orfa de uma execucao interrompida (pid ${dono:-desconhecido})."
    rm -rf "$LOCK"
    mkdir "$LOCK" || falhar "nao foi possivel criar a trava $LOCK"
  fi
  echo $$ > "$LOCK/pid"
  trap 'rm -rf "$LOCK"' EXIT
}

registrar() {
  printf '%s\t%s\t%s\t%s -> %s\t%s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$(id -un)" \
    "$BRANCH" "${ANTES:0:7}" "${DEPOIS:0:7}" "$1" >> "$HISTORICO"
}

instalar_dependencias() {
  log "Instalando dependencias e patches de GPU..."
  "$VENV/bin/python" -m pip install --quiet -r "$REPO/requirements.txt" \
    && "$VENV/bin/python" "$REPO/$PATCHES" \
    && "$VENV/bin/python" -m pip check
}

# Reproduz o ambiente do launchd (sem o PATH do usuario, python3 do venv) e
# carrega a mesma cadeia de imports de um job real.
validar() {
  local ambiente=(env -i "HOME=$HOME" "PATH=$VENV/bin:/usr/bin:/bin" "PYTHONPATH=$REPO")
  (cd "$REPO" \
    && "${ambiente[@]}" python3 -m docling_pipeline --help >/dev/null \
    && "${ambiente[@]}" python3 -c 'import docling_runtime.server')
}

reiniciar() {
  local pid_antigo pid_novo
  pid_antigo="$(pgrep -u "$(id -u)" -f "$PROC_SERVIDOR" || true)"
  log "Reiniciando o runner (pid ${pid_antigo:-nenhum})..."
  pkill -TERM -u "$(id -u)" -f "$PROC_SERVIDOR" || true
  for _ in {1..45}; do
    sleep 2
    pid_novo="$(pgrep -u "$(id -u)" -f "$PROC_SERVIDOR" || true)"
    if [ -n "$pid_novo" ] && [ "$pid_novo" != "$pid_antigo" ] \
      && curl -fsS --max-time 2 "$HEALTHZ" >/dev/null 2>&1; then
      log "Runner no ar (pid $pid_novo)."
      return 0
    fi
  done
  return 1
}

reverter() {
  log "Falha: $1. Voltando para ${ANTES:0:7}..."
  if [ -n "$BRANCH_ANTES" ]; then
    git -C "$REPO" checkout --quiet -B "$BRANCH_ANTES" "$ANTES"
  else
    git -C "$REPO" checkout --quiet --detach "$ANTES"
  fi
  if [ "$DEPS_MUDARAM" = sim ]; then
    instalar_dependencias || log "AVISO: falha ao reinstalar as dependencias anteriores."
  fi
  if [ "$REINICIADO" = sim ]; then
    reiniciar || log "AVISO: o runner nao voltou; veja $HOME/ocr-data/logs/docling-runner.err.log"
  else
    log "O runner nao chegou a ser reiniciado e segue na versao ${ANTES:0:7}."
  fi
  echo "$DEPOIS" > "$COMMIT_COM_FALHA"
  registrar "revertido: $1"
  exit 1
}

main() {
  BRANCH_ANTES="$(git -C "$REPO" symbolic-ref --short -q HEAD || true)"
  BRANCH="${1:-${BRANCH_ANTES:-main}}"
  git check-ref-format --branch "$BRANCH" >/dev/null 2>&1 || falhar "branch invalido: $BRANCH"

  adquirir_trava

  launchctl print "$SERVICO" >/dev/null 2>&1 || falhar "o servico $SERVICO nao esta carregado no launchd"
  [ -z "$(git -C "$REPO" status --porcelain)" ] \
    || falhar "o clone $REPO tem alteracoes locais; ele e espelho do GitHub, nao bancada de trabalho"

  ANTES="$(git -C "$REPO" rev-parse HEAD)"
  git -C "$REPO" fetch --quiet origin "$BRANCH"
  DEPOIS="$(git -C "$REPO" rev-parse FETCH_HEAD)"
  if [ "$ANTES" = "$DEPOIS" ]; then
    log "Nada novo em origin/$BRANCH: o runner ja esta em ${ANTES:0:7}."
    exit 0
  fi
  if [ "$(cat "$COMMIT_COM_FALHA" 2>/dev/null || true)" = "$DEPOIS" ]; then
    log "O commit ${DEPOIS:0:7} ja falhou e foi revertido; aguardando um commit novo em" \
      "origin/$BRANCH (para tentar de novo: rm $COMMIT_COM_FALHA)."
    exit 0
  fi

  REINICIADO=nao
  DEPS_MUDARAM=nao
  git -C "$REPO" diff --quiet "$ANTES" "$DEPOIS" -- requirements.txt "$PATCHES" || DEPS_MUDARAM=sim

  while pgrep -f "$PROC_EXTRACAO" >/dev/null; do
    log "Extracao em andamento; aguardando terminar..."
    sleep 30
  done

  log "Atualizando ${ANTES:0:7} -> ${DEPOIS:0:7} ($BRANCH)..."
  git -C "$REPO" checkout --quiet -B "$BRANCH" "$DEPOIS"
  if [ "$DEPS_MUDARAM" = sim ]; then
    instalar_dependencias || reverter "falha ao instalar as dependencias"
  fi
  log "Validando o pipeline no ambiente do servico..."
  validar || reverter "o pipeline nao carrega no ambiente do servico"
  REINICIADO=sim
  reiniciar || reverter "o runner nao respondeu ao /healthz depois de reiniciar"

  rm -f "$COMMIT_COM_FALHA"
  registrar "ok"
  log "Runner atualizado: ${ANTES:0:7} -> ${DEPOIS:0:7}."
}

# O git pode reescrever este arquivo durante o checkout: chamar main e sair na
# mesma linha garante que o bash ja leu o script inteiro antes disso.
main "$@"; exit $?
