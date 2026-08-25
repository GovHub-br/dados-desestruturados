// Estado da execucao em duas alturas: o pipeline da home fala a lingua do
// usuario; a rastreabilidade guarda os termos tecnicos.

export const FLOW = ['origin', 'extraction', 'evidence', 'resolution', 'fallback', 'result'];

const PIPELINE_FLOW = ['origin', 'extraction', 'evidence', 'resolution', 'result'];

// Rotulo curto para a home; o texto completo do backend fica na rastreabilidade.
const SHORT_LABEL = {
  origin: 'Recebendo PDF',
  extraction: 'Extraindo',
  evidence: 'Reunindo evidências',
  resolution: 'Validando',
  fallback: 'Corrigindo layout',
  result: 'Concluído',
};

// Curto de proposito: cada rotulo precisa caber sob o icone sem quebrar linha.
const STEP_STATE_LABEL = {
  origin: 'Recebendo',
  extraction: 'Extraindo',
  evidence: 'Reunindo',
  resolution: 'Validando',
  result: 'Concluído',
};

const RESULT_ICON = {
  idle: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3 5 6v6c0 4 2.9 6.9 7 8 4.1-1.1 7-4 7-8V6l-7-3Z"/></svg>',
  success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 4 4L19 7"/></svg>',
  running: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 7v5l3 2"/><circle cx="12" cy="12" r="9"/></svg>',
  failed: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 8v5m0 3h.01"/><circle cx="12" cy="12" r="9"/></svg>',
};

const $ = selector => document.querySelector(selector);
const all = selector => [...document.querySelectorAll(selector)];

const statusPill = () => $('#lineage-status');

function renderStatus(text, { failed = false } = {}) {
  const pill = statusPill();
  pill.classList.toggle('failed', failed);
  pill.replaceChildren();
  const dot = document.createElement('i');
  dot.setAttribute('aria-hidden', 'true');
  pill.append(dot, document.createTextNode(text));
}

/** Rotulo curto da etapa, para caber em uma linha na faixa de resultado. */
export const shortLabel = stage => SHORT_LABEL[stage] || 'Em andamento';

export function setMode(mode) {
  const stage = $('#stage');
  if (!stage) return;
  // A arte de repouso é parte da identidade visual da página e não depende
  // das preferências de tema do sistema. Os cartões vivos aparecem apenas
  // quando há uma ação ou execução em andamento.
  stage.dataset.mode = mode === 'art' ? 'art' : 'live';
}

export function setPolling(active) {
  statusPill().classList.toggle('polling', active);
  $('#pipeline-status').dataset.state = active ? 'running' : 'idle';
}

export function setStatusText(text) {
  renderStatus(text);
}

export function setAppliedContract(text) {
  $('#applied-contract').textContent = text;
}

export function setStage(stage, label, { failed = false } = {}) {
  setMode('live');
  const index = FLOW.indexOf(stage);

  // Pipeline da home: fallback continua exibido como "Validação" em andamento.
  const pipelineStage = stage === 'fallback' ? 'resolution' : stage;
  const pipelineIndex = PIPELINE_FLOW.indexOf(pipelineStage);
  all('.pipeline-step').forEach(step => {
    const position = PIPELINE_FLOW.indexOf(step.dataset.stage);
    const isCurrent = position === pipelineIndex;
    const isDone = position < pipelineIndex || (stage === 'result' && position <= pipelineIndex);
    // No fim da jornada todas as etapas ficam concluidas, inclusive a ultima.
    step.dataset.state = isCurrent && failed ? 'failed' : isDone ? 'done' : isCurrent ? 'current' : 'idle';
    // Etapas ainda nao alcancadas ficam em silencio: cinco "Aguardando"
    // lado a lado sao ruido, e o cartao ja diz o estado geral.
    step.querySelector('.pipeline-state').textContent = isCurrent && failed
      ? 'Falhou'
      : isDone
        ? 'Concluído'
        : isCurrent
          ? STEP_STATE_LABEL[step.dataset.stage] || 'Em andamento'
          : '';
  });

  const pipelineStatus = $('#pipeline-status');
  pipelineStatus.dataset.state = failed ? 'failed' : stage === 'result' ? 'idle' : 'running';
  $('#pipeline-status-text').textContent = failed ? 'Execução interrompida' : SHORT_LABEL[stage] || 'Em andamento';

  // Grafo tecnico da rastreabilidade.
  all('.lineage-node').forEach(node => {
    const position = FLOW.indexOf(node.dataset.stage);
    const isCurrent = node.dataset.stage === stage;
    node.classList.toggle('current', isCurrent && !failed);
    node.classList.toggle('failed', isCurrent && failed);
    node.classList.toggle('queued', position >= 0 && position < index);
  });

  renderStatus(label, { failed });
}

export function markFallbackSeen() {
  document.querySelector('.lineage-node[data-stage="fallback"]')?.classList.add('queued');
}

/** A superficie inferior do cartao mostra sempre o estado real da execucao. */
export function showResult({ kind = 'success', title, detail, action = 'Ver resultado →' }) {
  setMode('live');
  const icon = $('#result-icon');
  icon.classList.toggle('success', kind === 'success');
  icon.classList.toggle('failed', kind === 'failed');
  icon.innerHTML = RESULT_ICON[kind] || RESULT_ICON.running;
  $('#result-title').textContent = title;
  $('#result-detail').textContent = detail;
  const button = $('#result-action');
  button.textContent = action;
  button.hidden = false;
}

/** Estado de repouso: sem execucao, sem acao — so o convite e a garantia. */
export function idleResult() {
  const icon = $('#result-icon');
  icon.classList.remove('success', 'failed');
  icon.innerHTML = RESULT_ICON.idle;
  $('#result-title').textContent = 'Pronto para receber PDF';
  $('#result-detail').textContent = 'Original e checksum preservados.';
  $('#result-action').hidden = true;
}

export function reset() {
  all('.pipeline-step').forEach(step => {
    step.dataset.state = 'idle';
    step.querySelector('.pipeline-state').textContent = '';
  });
  $('#pipeline-status').dataset.state = 'idle';
  $('#pipeline-status-text').textContent = 'Pronto para receber';
  all('.lineage-node').forEach(node => node.classList.remove('current', 'queued', 'failed'));
  document.querySelector('.lineage-node[data-stage="origin"]')?.classList.add('current');
  renderStatus('Nenhuma execução em andamento.');
  idleResult();
  setMode('art');
}
