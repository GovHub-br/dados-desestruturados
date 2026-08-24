// Estado visual da linhagem: painel do hero, etapas e nos do grafo.

export const LINEAGE_FLOW = ['origin', 'extraction', 'evidence', 'resolution', 'fallback', 'result'];

const STAGE_TITLE = {
  origin: 'Recebendo PDF',
  extraction: 'Extração',
  evidence: 'Evidências',
  resolution: 'Resolução',
  fallback: 'Fallback LLM',
  result: 'Resultado',
};

const STAGE_STATE = {
  origin: 'Recebendo',
  extraction: 'Em andamento',
  evidence: 'Em andamento',
  resolution: 'DAG 2',
  fallback: 'DAG 3',
  result: 'Concluído',
};

const nodes = () => [...document.querySelectorAll('.lineage-node')];
const stages = () => [...document.querySelectorAll('.hero-stage')];

const status = () => document.querySelector('#lineage-status');
const live = () => document.querySelector('#panel-live');

function renderStatus(text, { failed = false } = {}) {
  const element = status();
  element.classList.toggle('failed', failed);
  element.replaceChildren();
  const dot = document.createElement('i');
  dot.setAttribute('aria-hidden', 'true');
  element.append(dot, document.createTextNode(text));
}

export function setPolling(active) {
  status().classList.toggle('polling', active);
  live().classList.toggle('polling', active);
}

export function setStage(stage, label, { failed = false } = {}) {
  const currentIndex = LINEAGE_FLOW.indexOf(stage);

  nodes().forEach(node => {
    const index = LINEAGE_FLOW.indexOf(node.dataset.stage);
    const isCurrent = node.dataset.stage === stage;
    node.classList.toggle('current', isCurrent && !failed);
    node.classList.toggle('failed', isCurrent && failed);
    node.classList.toggle('queued', index >= 0 && index < currentIndex);
  });

  stages().forEach(step => {
    const state = step.dataset.stage;
    const index = LINEAGE_FLOW.indexOf(state);
    const isCurrent = state === stage || (stage === 'fallback' && state === 'resolution');
    const done = index >= 0 && index < currentIndex;
    step.classList.toggle('active', isCurrent);
    const stateLabel = step.querySelector('.stage-state');
    stateLabel.className = `stage-state${isCurrent ? ' active' : done ? ' done' : ''}`;
    stateLabel.textContent = isCurrent ? (STAGE_STATE[stage] || 'Em andamento') : done ? 'Concluído' : 'Aguardando';
  });

  document.querySelector('#panel-stage').textContent = STAGE_TITLE[stage] || 'Aguardando';
  renderStatus(label, { failed });
}

export function markFallbackSeen() {
  document.querySelector('[data-stage="fallback"].lineage-node')?.classList.add('queued');
}

export function setRun(dagRunId) {
  if (!dagRunId) return;
  document.querySelector('#panel-run').textContent = String(dagRunId).slice(-8);
}

export function setStartedNow() {
  document.querySelector('#panel-start').textContent =
    new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

export function setStatusText(text) {
  renderStatus(text);
}
