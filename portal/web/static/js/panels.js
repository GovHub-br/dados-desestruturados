// Progressive disclosure: os formularios completos vivem fora da home e
// expandem no lugar, mantendo a continuidade espacial.

import { scrollTo } from './motion.js';

const panels = new Map();
let lastTrigger = null;

function apply(panel, open) {
  const drawer = panel.querySelector('.panel-drawer > div');
  panel.dataset.open = String(open);
  panel.querySelector('[data-open-panel]')?.setAttribute('aria-expanded', String(open));
  drawer.inert = !open;
  drawer.setAttribute('aria-hidden', String(!open));
}

function closeAll() {
  panels.forEach(panel => apply(panel, false));
}

export function openPanel(name, { trigger = null } = {}) {
  const panel = panels.get(name);
  if (!panel) return;
  lastTrigger = trigger || lastTrigger;
  panels.forEach(item => apply(item, item === panel));
  scrollTo(panel);
  panel.querySelector('input:not([type=file])')?.focus({ preventScroll: true });
}

export function closePanel(panel) {
  apply(panel, false);
  // O foco volta para quem abriu: ninguem fica perdido no fim da pagina.
  lastTrigger?.focus?.();
}

export function setupPanels() {
  document.querySelectorAll('[data-panel]').forEach(panel => {
    panels.set(panel.dataset.panel, panel);
    apply(panel, false);
    panel.querySelector('[data-close-panel]')?.addEventListener('click', () => closePanel(panel));
  });

  document.querySelectorAll('[data-open-panel]').forEach(trigger => {
    trigger.addEventListener('click', event => {
      event.preventDefault();
      openPanel(trigger.dataset.openPanel, { trigger });
    });
  });

  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const open = [...panels.values()].find(panel => panel.dataset.open === 'true');
    if (open) closePanel(open);
  });

  // O endereco tambem abre o caminho: /#envio chega com o formulario pronto.
  const openFromHash = () => {
    const name = window.location.hash.replace('#', '');
    if (panels.has(name)) openPanel(name);
    else closeAll();
  };
  openFromHash();
  window.addEventListener('hashchange', openFromHash);
}

export function setupLineage() {
  const section = document.querySelector('#rastreabilidade');
  const details = document.querySelector('#lineage-details');
  const toggle = document.querySelector('#lineage-toggle');
  const close = document.querySelector('#lineage-close');
  const content = details.firstElementChild;

  const applyDetails = open => {
    details.dataset.open = String(open);
    toggle.setAttribute('aria-expanded', String(open));
    toggle.textContent = open ? 'Ocultar detalhes técnicos' : 'Ver detalhes técnicos';
    content.inert = !open;
    content.setAttribute('aria-hidden', String(!open));
  };

  applyDetails(false);
  toggle.addEventListener('click', () => applyDetails(details.dataset.open !== 'true'));

  /** Revela a secao tecnica; `details` abre tambem o grafo. */
  const show = ({ details: openDetails = false, scroll = false } = {}) => {
    section.dataset.visible = 'true';
    if (openDetails) applyDetails(true);
    if (scroll) scrollTo(section);
  };

  /** Esconde a secao inteira, igual aos demais paineis: sem estado preso na tela. */
  const hide = () => {
    section.dataset.visible = 'false';
    // O hash so significa "abrir"; sem isso, voltar para a pagina reabriria
    // a secao que a pessoa acabou de fechar.
    if (window.location.hash === '#rastreabilidade') {
      history.replaceState(null, '', window.location.pathname + window.location.search);
    }
  };

  close.addEventListener('click', () => hide());

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && section.dataset.visible === 'true') hide();
  });

  document.querySelectorAll('[data-open-lineage]').forEach(trigger => {
    trigger.addEventListener('click', () => show({ details: true, scroll: true }));
  });

  if (window.location.hash === '#rastreabilidade') show({ details: true });
  window.addEventListener('hashchange', () => {
    if (window.location.hash === '#rastreabilidade') show({ details: true, scroll: true });
  });

  return { show, hide };
}
