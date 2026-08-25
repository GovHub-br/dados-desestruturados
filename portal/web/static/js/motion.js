// Preferencias de movimento, feedback tatil e entrada da pagina.

const reduceQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

export const prefersReducedMotion = () => reduceQuery.matches;

export function scrollTo(element) {
  element.scrollIntoView({
    behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    block: 'start',
  });
}

// Haptico apenas em momentos com significado (commit, erro), no mesmo instante
// da mudanca visual para que os sentidos concordem.
export function haptic(kind) {
  if (prefersReducedMotion() || typeof navigator.vibrate !== 'function') return;
  navigator.vibrate(kind === 'error' ? [12, 60, 12] : 12);
}

// Entrada curta em cascata: apenas opacidade e translacao.
export function revealOnLoad() {
  const targets = [...document.querySelectorAll('[data-reveal]')];
  if (prefersReducedMotion()) {
    targets.forEach(target => target.classList.add('revealed'));
    return;
  }
  requestAnimationFrame(() => targets.forEach(target => target.classList.add('revealed')));
}

// O header ganha material e fio de borda quando o conteudo passa por baixo.
export function watchHeaderScroll() {
  const header = document.querySelector('#header');
  if (!header) return;
  let ticking = false;
  const update = () => {
    header.dataset.scrolled = String(window.scrollY > 8);
    ticking = false;
  };
  update();
  window.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(update);
  }, { passive: true });
}
