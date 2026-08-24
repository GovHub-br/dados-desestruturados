// Ligacao entre a interface e as rotas do portal.

import * as api from './api.js';
import { setupJourneys, setupLineageDetails } from './accordion.js';
import * as lineage from './lineage.js';
import { clearMessage, showMessage } from './messages.js';
import { createProgress } from './progress.js';
import * as trace from './trace.js';

const $ = selector => document.querySelector(selector);

const domainInput = $('#domain');
const contractInput = $('#contract');
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

const details = setupLineageDetails();
setupJourneys();

let knownDomains = [];

const normalizeDomain = value => value.trim().toLowerCase();

const notice = (kind, text) => {
  domainNotice.className = `domain-notice ${kind}`;
  domainNotice.textContent = text;
};

const fillOptions = (list, values) => {
  list.replaceChildren(...values.map(value => {
    const option = document.createElement('option');
    option.value = value;
    return option;
  }));
};

function checkDomain() {
  const domain = normalizeDomain(domainInput.value);
  if (!domain) {
    notice('info', 'Informe um domínio para consultar os contratos publicados.');
    return false;
  }
  if (knownDomains.includes(domain)) {
    notice('info', `Domínio reconhecido. Escolha uma das versões publicadas para ${domain}.`);
    return true;
  }
  notice('warning', `O domínio “${domain}” ainda não possui contrato publicado. Domínios disponíveis: ${knownDomains.join(', ') || 'nenhum'}. Para utilizá-lo, publique primeiro um contrato semântico abaixo.`);
  versionsList.replaceChildren();
  contractInput.value = '';
  return false;
}

async function loadVersions() {
  const domain = normalizeDomain(domainInput.value);
  if (!knownDomains.includes(domain)) {
    checkDomain();
    return;
  }
  try {
    const versions = await api.listContractVersions(domain);
    fillOptions(versionsList, versions);
    if (versions.length && !versions.includes(contractInput.value)) contractInput.value = versions[0];
    checkDomain();
  } catch {
    notice('warning', 'Não foi possível listar as versões agora. A API verificará o contrato antes da extração.');
  }
}

async function loadDomains() {
  try {
    knownDomains = await api.listDomains();
    fillOptions(domainsList, knownDomains);
    await loadVersions();
  } catch {
    notice('warning', 'Não foi possível carregar os domínios agora. A validação será feita ao enviar.');
  }
}

domainInput.addEventListener('input', checkDomain);
domainInput.addEventListener('change', loadVersions);
domainInput.addEventListener('blur', loadVersions);

uploadForm.addEventListener('submit', async event => {
  event.preventDefault();
  if (!checkDomain()) {
    showMessage(
      uploadOut,
      'error',
      'Envio interrompido',
      'Escolha um domínio com contrato publicado ou publique primeiro um contrato semântico.',
    );
    return;
  }

  uploadButton.disabled = true;
  uploadButton.textContent = 'Enviando…';
  clearMessage(uploadOut);
  uploadProgress.start('Preparando envio…');
  lineage.setStage('origin', 'Recebendo documento');
  details.show();

  try {
    const payload = await api.uploadDocument(new FormData(uploadForm), ratio => uploadProgress.set(ratio));
    uploadProgress.waiting('Agendando a extração no Airflow…');
    lineage.setRun(payload.dag_run_id);
    lineage.setStartedNow();
    lineage.setStage('extraction', 'Extração agendada no Airflow');
    showMessage(
      uploadOut,
      'success',
      'Execução iniciada',
      `Documento ${payload.document_id} · DAG run ${payload.dag_run_id}`,
    );
    trace.start({
      domain: normalizeDomain(domainInput.value),
      entitySlug: $('#slug').value.trim().toLowerCase(),
      documentId: payload.document_id,
      dagRunId: payload.dag_run_id,
    });
  } catch (error) {
    lineage.setStage('origin', 'Envio não iniciado', { failed: true });
    showMessage(uploadOut, 'error', 'Não foi possível iniciar a execução', error.message);
  } finally {
    uploadProgress.done();
    uploadButton.disabled = false;
    uploadButton.textContent = 'Enviar e iniciar extração';
  }
});

contractForm.addEventListener('submit', async event => {
  event.preventDefault();
  contractButton.disabled = true;
  contractButton.textContent = 'Validando…';
  clearMessage(contractOut);
  contractProgress.start('Enviando contrato…');

  try {
    const payload = await api.publishContract(new FormData(contractForm), ratio => contractProgress.set(ratio));
    showMessage(
      contractOut,
      'success',
      'Contrato publicado',
      `Domínio ${payload.domain} · versão ${payload.version}`,
    );
    if (!knownDomains.includes(payload.domain)) {
      knownDomains = [...knownDomains, payload.domain].sort();
      fillOptions(domainsList, knownDomains);
    }
    domainInput.value = payload.domain;
    contractInput.value = payload.version;
    await loadVersions();
  } catch (error) {
    showMessage(contractOut, 'error', 'Contrato não publicado', error.message);
  } finally {
    contractProgress.done();
    contractButton.disabled = false;
    contractButton.textContent = 'Validar e publicar contrato';
  }
});

loadDomains();
if (trace.resume()) details.show();
