// O Airflow cria novos run IDs quando uma DAG dispara a proxima. O portal mantem
// o documento como identidade da jornada e consulta o backend periodicamente.

import { fetchTrace } from './api.js';
import * as lineage from './lineage.js';

const STORAGE_KEY = 'portal.execution-trace';
const POLL_INTERVAL_MS = 4000;

let active = null;
let timer = null;

function persist() {
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(active));
  } catch {
    // Sessao sem armazenamento (janela privada): a rastreabilidade segue em memoria.
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
  lineage.setPolling(false);
}

function render(trace) {
  const failed = trace.state === 'failed';
  lineage.setStage(trace.stage, trace.label, { failed });
  if (active?.fallbackSeen && trace.stage === 'resolution') lineage.markFallbackSeen();
  if (trace.stage === 'fallback') active.fallbackSeen = true;
  lineage.setRun(trace.run?.dag_run_id);
}

async function poll() {
  if (!active) return;
  lineage.setPolling(true);
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
    lineage.setStatusText('Atualizando rastreabilidade…');
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
