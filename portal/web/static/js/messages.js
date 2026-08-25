// Mensagens de status: texto de interface com titulo e detalhe, nunca um log.

import { haptic } from './motion.js';

export function showMessage(element, kind, title, detail = '') {
  element.dataset.kind = kind;
  element.replaceChildren();

  const heading = document.createElement('strong');
  heading.className = 'message-title';
  heading.textContent = title;
  element.append(heading);

  if (detail) {
    const paragraph = document.createElement('p');
    paragraph.className = 'message-detail';
    paragraph.textContent = detail;
    element.append(paragraph);
  }

  haptic(kind);
  if (kind === 'error') element.focus();
}

export function clearMessage(element) {
  delete element.dataset.kind;
  element.replaceChildren();
}
