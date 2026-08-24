// Acesso as rotas do portal. Uploads usam XMLHttpRequest porque `fetch` nao
// expoe progresso de envio, e um PDF de 50 MB precisa de feedback continuo.

function describeFailure(payload, status) {
  const detail = payload && payload.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map(item => item && item.msg).filter(Boolean);
    if (messages.length) return messages.join(' ');
  }
  return `O portal respondeu com o status ${status}.`;
}

function send(method, url, body, { onProgress } = {}) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open(method, url);
    request.responseType = 'json';
    if (onProgress && request.upload) {
      request.upload.addEventListener('progress', event => {
        onProgress(event.lengthComputable ? event.loaded / event.total : null);
      });
    }
    request.addEventListener('load', () => {
      const payload = request.response || {};
      if (request.status >= 200 && request.status < 300) resolve(payload);
      else reject(new Error(describeFailure(payload, request.status)));
    });
    request.addEventListener('error', () => reject(new Error('Não foi possível falar com o portal.')));
    request.addEventListener('timeout', () => reject(new Error('O portal demorou demais para responder.')));
    request.send(body);
  });
}

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(await describeResponse(response));
  return response.json();
}

async function describeResponse(response) {
  try {
    return describeFailure(await response.json(), response.status);
  } catch {
    return `O portal respondeu com o status ${response.status}.`;
  }
}

export const listDomains = () => getJSON('/api/domains');

export const listContractVersions = async domain => {
  const contracts = await getJSON(`/api/contracts?domain=${encodeURIComponent(domain)}`);
  return contracts.map(contract => contract.version);
};

export const publishContract = (formData, onProgress) =>
  send('POST', '/api/contracts', formData, { onProgress });

export const uploadDocument = (formData, onProgress) =>
  send('POST', '/api/documents', formData, { onProgress });

export const fetchTrace = async params => {
  const response = await fetch(`/api/execution-trace?${new URLSearchParams(params)}`);
  const payload = await response.json();
  if (!response.ok) throw new Error(describeFailure(payload, response.status));
  return payload;
};
