// Ligacao entre a interface e as rotas do portal.

import * as api from './api.js';
import { attachPicker, createFileField } from './dropzone.js';
import * as execution from './execution.js';
import { clearMessage, showMessage } from './messages.js';
import { revealOnLoad, watchHeaderScroll } from './motion.js';
import { openPanel, setupLineage, setupPanels } from './panels.js';
import { createProgress } from './progress.js';
import * as trace from './trace.js';

const $ = selector => document.querySelector(selector);

const domainInput = $('#domain');
const versionInput = $('#contract');
const domainStatus = $('#domain-status');
const versionStatus = $('#contract-status');
const domainNotice = $('#domain-notice');
const domainsList = $('#known-domains');
const versionsList = $('#published-versions');

const uploadForm = $('#upload');
const uploadButton = $('#submit');
const uploadOut = $('#out');
const uploadProgress = createProgress($('#upload-progress'), $('#upload-progress-bar'), $('#upload-progress-label'));

const contractForm = $('#contract-upload');
const contractButton = $('#contract-submit');
const contractOut = $('#contract-out');
const contractProgress = createProgress($('#contract-progress'), $('#contract-progress-bar'), $('#contract-progress-label'));

const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 4 4L19 7"/></svg>';
const ALERT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 8v5m0 3h.01"/><circle cx="12" cy="12" r="9"/></svg>';

setupPanels();
const lineage = setupLineage();
watchHeaderScroll();
revealOnLoad();
execution.reset();

let knownDomains = [];
let availableVersions = [];
// Quando a lista de dominios nao carrega, a validacao volta a ser do backend:
// travar o formulario deixaria a pessoa sem saida.
let domainsLoaded = false;

const normalizeDomain = value => value.trim().toLowerCase();

function setFieldStatus(element, state, text, icon = '') {
  element.dataset.state = state;
  element.innerHTML = icon;
  element.append(document.createTextNode(text));
}

// O input de arquivo e visualmente substituido pela dropzone, entao a validacao
// nativa nao teria onde aparecer: a mensagem vai para a propria caixa.
function requireFile(input, dropzone, output, message) {
  const chosen = Boolean(input.files && input.files.length);
  input.setAttribute('aria-invalid', String(!chosen));
  dropzone.classList.toggle('invalid', !chosen);
  if (!chosen) {
    showMessage(output, 'error', 'Arquivo não selecionado', message);
    dropzone.scrollIntoView({ block: 'center', behavior: 'auto' });
  }
  return chosen;
}

function setNotice(kind, text) {
  if (!kind) {
    delete domainNotice.dataset.kind;
    domainNotice.textContent = '';
    return;
  }
  domainNotice.dataset.kind = kind;
  domainNotice.textContent = text;
}

function fillOptions(list, values) {
  list.replaceChildren(...values.map(value => {
    const option = document.createElement('option');
    option.value = value;
    return option;
  }));
}

function updateAppliedContract() {
  const domain = normalizeDomain(domainInput.value);
  const version = versionInput.value.trim();
  if (domain && version) execution.setAppliedContract(`${domain} · ${version}`);
  else if (domain) execution.setAppliedContract(domain);
  else execution.setAppliedContract('selecione um domínio');
}

/** Estados do par domínio → versão, sempre explicando por que algo está travado. */
function checkDomain() {
  const domain = normalizeDomain(domainInput.value);

  if (!domain) {
    setFieldStatus(domainStatus, 'idle', 'Informe um domínio para consultar os contratos publicados.');
    setVersionState('disabled');
    setNotice(null);
    updateAppliedContract();
    return false;
  }

  if (knownDomains.includes(domain)) {
    setFieldStatus(domainStatus, 'ok', 'Domínio reconhecido', CHECK);
    setNotice(null);
    updateAppliedContract();
    return true;
  }

  if (!domainsLoaded) {
    setFieldStatus(domainStatus, 'idle', 'Lista de domínios indisponível; a validação será feita ao enviar.');
    setNotice(null);
    updateAppliedContract();
    return true;
  }

  setFieldStatus(domainStatus, 'invalid', 'Nenhum contrato publicado para este domínio.', ALERT);
  setNotice('warning', `O domínio “${domain}” ainda não possui contrato publicado. Domínios disponíveis: ${knownDomains.join(', ') || 'nenhum'}. Para utilizá-lo, publique primeiro um contrato semântico.`);
  setVersionState('disabled');
  versionsList.replaceChildren();
  versionInput.value = '';
  updateAppliedContract();
  return false;
}

function setVersionState(state) {
  if (state === 'disabled') {
    versionInput.disabled = true;
    setFieldStatus(versionStatus, 'idle', 'Escolha um domínio com contrato publicado.');
    return;
  }
  if (state === 'loading') {
    versionInput.disabled = true;
    setFieldStatus(versionStatus, 'loading', 'Buscando versões publicadas…');
    return;
  }
  if (state === 'empty') {
    versionInput.disabled = true;
    setFieldStatus(versionStatus, 'invalid', 'Nenhuma versão publicada para este domínio.', ALERT);
    return;
  }
  versionInput.disabled = false;
  const total = availableVersions.length;
  setFieldStatus(versionStatus, 'ok', `${total} ${total === 1 ? 'versão disponível' : 'versões disponíveis'}`, CHECK);
}

async function loadVersions() {
  const domain = normalizeDomain(domainInput.value);
  if (!domainsLoaded) {
    checkDomain();
    return;
  }
  if (!knownDomains.includes(domain)) {
    checkDomain();
    return;
  }
  setVersionState('loading');
  try {
    availableVersions = await api.listContractVersions(domain);
    fillOptions(versionsList, availableVersions);
    if (!availableVersions.length) {
      setVersionState('empty');
    } else {
      if (!availableVersions.includes(versionInput.value)) versionInput.value = availableVersions[0];
      setVersionState('available');
    }
    checkDomain();
  } catch {
    versionInput.disabled = false;
    setFieldStatus(versionStatus, 'invalid', 'Não foi possível listar as versões agora; o envio ainda será validado.', ALERT);
  }
  updateAppliedContract();
}

async function loadDomains() {
  try {
    knownDomains = await api.listDomains();
    domainsLoaded = true;
    fillOptions(domainsList, knownDomains);
    await loadVersions();
  } catch {
    domainsLoaded = false;
    setFieldStatus(domainStatus, 'invalid', 'Não foi possível carregar os domínios agora; a validação será feita ao enviar.', ALERT);
    versionInput.disabled = false;
    setFieldStatus(versionStatus, 'idle', 'Informe a versão publicada do contrato.');
  }
}

domainInput.addEventListener('input', checkDomain);
domainInput.addEventListener('change', loadVersions);
domainInput.addEventListener('blur', loadVersions);
versionInput.addEventListener('input', updateAppliedContract);

// Um único input de arquivo, duas superfícies: a do hero e a do formulário.
createFileField($('#pdf'), [$('#hero-dropzone'), $('#pdf-dropzone')], {
  onChange: file => {
    if (!file) return;
    // Com arquivo escolhido a jornada comecou: a ilustracao sai de cena.
    execution.setMode('live');
    openPanel('envio');
  },
});
createFileField($('#contract-file'), [$('#contract-dropzone')]);

uploadForm.addEventListener('submit', async event => {
  event.preventDefault();

  if (!checkDomain()) {
    showMessage(uploadOut, 'error', 'Envio interrompido', 'Escolha um domínio com contrato publicado ou publique primeiro um contrato semântico.');
    return;
  }
  if (!requireFile($('#pdf'), $('#pdf-dropzone'), uploadOut, 'Escolha o arquivo PDF do documento antes de enviar.')) return;
  if (!uploadForm.reportValidity()) return;

  uploadButton.disabled = true;
  uploadButton.textContent = 'Enviando…';
  clearMessage(uploadOut);
  uploadProgress.start('Preparando envio…');
  execution.setStage('origin', 'Recebendo documento');
  execution.showResult({ kind: 'running', title: 'Enviando documento', detail: 'Preservando o original', action: 'Acompanhar →' });

  try {
    const payload = await api.uploadDocument(new FormData(uploadForm), ratio => uploadProgress.set(ratio));
    uploadProgress.waiting('Agendando a extração…');
    execution.setStage('extraction', 'Extração agendada no Airflow');
    showMessage(uploadOut, 'success', 'Execução iniciada', `Documento ${payload.document_id} · execução ${payload.dag_run_id}`);
    lineage.show({ details: true });
    trace.start({
      domain: normalizeDomain(domainInput.value),
      entitySlug: $('#slug').value.trim().toLowerCase(),
      documentId: payload.document_id,
      dagRunId: payload.dag_run_id,
    });
  } catch (error) {
    execution.setStage('origin', 'Envio não iniciado', { failed: true });
    execution.showResult({ kind: 'failed', title: 'Envio não iniciado', detail: 'Veja os detalhes no formulário', action: 'Ver detalhes →' });
    showMessage(uploadOut, 'error', 'Não foi possível iniciar a execução', error.message);
  } finally {
    uploadProgress.done();
    uploadButton.disabled = false;
    uploadButton.textContent = 'Enviar e iniciar extração';
  }
});

contractForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (!requireFile($('#contract-file'), $('#contract-dropzone'), contractOut, 'Escolha o arquivo JSON do contrato antes de publicar.')) return;
  if (!contractForm.reportValidity()) return;

  contractButton.disabled = true;
  contractButton.textContent = 'Validando…';
  clearMessage(contractOut);
  contractProgress.start('Enviando contrato…');

  try {
    const payload = await api.publishContract(new FormData(contractForm), ratio => contractProgress.set(ratio));
    showMessage(contractOut, 'success', 'Contrato publicado', `Domínio ${payload.domain} · versão ${payload.version}`);
    if (!knownDomains.includes(payload.domain)) {
      knownDomains = [...knownDomains, payload.domain].sort();
      fillOptions(domainsList, knownDomains);
    }
    domainInput.value = payload.domain;
    versionInput.value = payload.version;
    await loadVersions();
  } catch (error) {
    showMessage(contractOut, 'error', 'Contrato não publicado', error.message);
  } finally {
    contractProgress.done();
    contractButton.disabled = false;
    contractButton.textContent = 'Validar e publicar contrato';
  }
});

setVersionState('disabled');
loadDomains();
if (trace.resume()) lineage.show({ details: true });
