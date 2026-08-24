// Acordeao dos caminhos. A altura anima de 0fr a 1fr, o conteudo fechado sai
// da ordem de foco e o gatilho responde ao toque, nao so ao hover.

import { scrollTo } from './motion.js';

export function setupJourneys() {
  const cards = [...document.querySelectorAll('.journey-card')];

  const apply = (card, open) => {
    const trigger = card.querySelector('.journey-trigger');
    const panel = card.querySelector('.journey-form');
    card.classList.toggle('expanded', open);
    trigger.setAttribute('aria-expanded', String(open));
    panel.inert = !open;
    panel.setAttribute('aria-hidden', String(!open));
  };

  const setOpen = (card, open = true) => cards.forEach(item => apply(item, item === card && open));

  cards.forEach(card => {
    apply(card, false);
    card.querySelector('.journey-trigger').addEventListener('click', () => {
      setOpen(card, !card.classList.contains('expanded'));
    });
  });

  document.querySelectorAll('a[href="#envio"], a[href="#contratos"]').forEach(link => {
    link.addEventListener('click', event => {
      const card = document.querySelector(link.getAttribute('href'));
      if (!card) return;
      event.preventDefault();
      setOpen(card);
      scrollTo(card);
    });
  });
}

export function setupLineageDetails() {
  const details = document.querySelector('#lineage-details');
  const toggle = document.querySelector('#lineage-toggle');
  const content = details.firstElementChild;

  const apply = open => {
    details.dataset.open = String(open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.textContent = open ? 'Ocultar detalhes técnicos' : 'Ver detalhes técnicos';
    content.inert = !open;
    content.setAttribute('aria-hidden', String(!open));
  };

  apply(false);
  toggle.addEventListener('click', () => apply(details.dataset.open !== 'true'));

  return { show: () => apply(true) };
}
