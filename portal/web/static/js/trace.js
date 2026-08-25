// O Airflow cria novos run IDs quando uma DAG dispara a proxima. O portal mantem
// o documento como identidade da jornada e consulta o backend periodicamente.

import { fetchTrace } from './api.js';
import * as execution from './execution.js';

const STORAGE_KEY = 'portal.execution-trace';
const POLL_INTERVAL_MS = 4000;

let active = null;
let timer = null;

function persist() {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(active));
  } catch {
    // Janela privada ou armazenamento bloqueado: a jornada segue em memoria.
  }
}

function restore() {
  try {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    return stored ? JSON.parse(stored) : null;
  } catch {
    return null;
  }
}

function forget() {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nada a limpar.
  }
}

export function stop() {
  if (timer) {
    window.clearTimeout(timer);
    timer = null;
  }
  execution.setPolling(false);
}

function render(trace) {
  const failed = trace.state === 'failed';
  execution.setStage(trace.stage, trace.label, { failed });

  if (active?.fallbackSeen && trace.stage === 'resolution') execution.markFallbackSeen();
  if (trace.stage === 'fallback') active.fallbackSeen = true;

  // A faixa diz o essencial em uma linha; o rotulo tecnico completo do backend
  // continua visivel na etiqueta de rastreabilidade.
  if (failed) {
    execution.showResult({
      kind: 'failed',
      title: 'Execução interrompida',
      detail: 'Veja onde parou',
      action: 'Ver detalhes →',
    });
  } else if (trace.terminal) {
    execution.showResult({
      kind: 'success',
      title: 'Extração concluída',
      detail: 'Resultado pronto para consulta',
      action: 'Ver resultado →',
    });
  } else {
    execution.showResult({
      kind: 'running',
      title: 'Execução em andamento',
      detail: execution.shortLabel(trace.stage),
      action: 'Acompanhar →',
    });
  }
}

async function poll() {
  if (!active) return;
  execution.setPolling(true);
  try {
    const trace = await fetchTrace({
      domain: active.domain,
      entity_slug: active.entity_slug,
      document_id: active.document_id,
      dag_run_id: active.dag_run_id,
    });
    render(trace);
    persist();
    if (trace.terminal) {
      stop();
      return;
    }
  } catch {
    // Mantem o ultimo estagio valido e tenta de novo: uma indisponibilidade
    // temporaria do Airflow nao deve fazer a pessoa perder a rastreabilidade.
    execution.setStatusText('Atualizando rastreabilidade…');
  }
  timer = window.setTimeout(poll, POLL_INTERVAL_MS);
}

export function start({ domain, entitySlug, documentId, dagRunId }) {
  stop();
  active = {
    domain,
    entity_slug: entitySlug,
    document_id: documentId,
    dag_run_id: dagRunId,
    fallbackSeen: false,
  };
  persist();
  poll();
}

export function resume() {
  const stored = restore();
  if (!stored?.domain || !stored?.entity_slug || !stored?.document_id || !stored?.dag_run_id) {
    if (stored) forget();
    return false;
  }
  active = stored;
  poll();
  return true;
}
