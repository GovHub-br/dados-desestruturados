// Preferencias de movimento e feedback multimodal.
// Movimento reduzido troca deslocamento por transicoes curtas; nunca remove o feedback.

const reduceQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

export const prefersReducedMotion = () => reduceQuery.matches;

export function scrollTo(element) {
  element.scrollIntoView({
    behavior: prefersReducedMotion() ? 'auto' : 'smooth',
    block: 'start',
  });
}

// Haptico so em momentos com significado (commit, erro), e nunca sozinho:
// dispara no mesmo quadro da mudanca visual para que os sentidos concordem.
export function haptic(kind) {
  if (prefersReducedMotion() || typeof navigator.vibrate !== 'function') return;
  navigator.vibrate(kind === 'error' ? [12, 60, 12] : 12);
}
