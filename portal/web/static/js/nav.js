// Menu de navegacao em telas estreitas: a mesma lista de links do header,
// revelada sob a faixa roxa. Em telas largas o botao nao existe visualmente
// e o menu volta a ser a barra horizontal.

const header = document.querySelector('.header');
const toggle = document.querySelector('.nav-toggle');
const nav = document.querySelector('#site-nav');
const narrow = window.matchMedia('(max-width: 720px)');

function setOpen(open) {
  if (!header || !toggle) return;
  header.dataset.menuOpen = String(open);
  toggle.setAttribute('aria-expanded', String(open));
  toggle.setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
}

export function setupNav() {
  if (!header || !toggle || !nav) return;
  setOpen(false);

  toggle.addEventListener('click', () => setOpen(header.dataset.menuOpen !== 'true'));

  // Escolher um destino fecha o menu: o conteudo aparece sem a lista por cima.
  nav.addEventListener('click', event => {
    if (event.target.closest('a')) setOpen(false);
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && header.dataset.menuOpen === 'true') {
      setOpen(false);
      toggle.focus();
    }
  });

  // Toque fora da faixa fecha o menu.
  document.addEventListener('pointerdown', event => {
    if (header.dataset.menuOpen === 'true' && !header.contains(event.target)) setOpen(false);
  });

  // Ao alargar a janela o menu horizontal reaparece; nada fica preso aberto.
  narrow.addEventListener('change', () => { if (!narrow.matches) setOpen(false); });
}

setupNav();
