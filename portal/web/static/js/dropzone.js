// Dropzone: a pele do input de arquivo nativo. O input continua sendo o
// controle real enviado no FormData; aqui trocamos apenas a aparencia,
// aceitamos arrastar e mostramos o arquivo escolhido sem mudar de tamanho.

const UNITS = ['B', 'KB', 'MB', 'GB'];

export function formatSize(bytes) {
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 10 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${UNITS[unit]}`;
}

const CHECK_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12 4 4L19 7"/></svg>';

function accepts(input, file) {
  const rules = (input.accept || '').split(',').map(item => item.trim().toLowerCase()).filter(Boolean);
  if (!rules.length) return true;
  const name = file.name.toLowerCase();
  const type = (file.type || '').toLowerCase();
  return rules.some(rule => (rule.startsWith('.') ? name.endsWith(rule) : type === rule));
}

/**
 * Liga um elemento ao input sem alterar o que ele mostra: serve para
 * superficies que ja tem arte propria, como a ilustracao do hero.
 */
export function attachPicker(input, element) {
  if (!element) return;

  element.addEventListener('click', () => input.click());

  ['dragenter', 'dragover'].forEach(type => element.addEventListener(type, event => {
    event.preventDefault();
    element.dataset.dragover = 'true';
  }));
  ['dragleave', 'dragend', 'drop'].forEach(type => element.addEventListener(type, () => {
    delete element.dataset.dragover;
  }));
  element.addEventListener('drop', event => {
    event.preventDefault();
    const file = event.dataTransfer?.files?.[0];
    if (!file || !accepts(input, file)) return;
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  });
}

/**
 * Liga um input de arquivo a uma ou mais superficies visuais. Todas refletem o
 * mesmo estado porque o estado mora no input, nao na tela.
 */
export function createFileField(input, surfaces, { onChange } = {}) {
  const views = surfaces.filter(Boolean).map(root => ({
    root,
    idle: root.innerHTML,
    // Superficies sem input adjacente sao o proprio controle de teclado.
    standalone: root.getAttribute('role') === 'button',
  }));

  const openPicker = () => input.click();

  const clear = () => {
    input.value = '';
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };

  const assign = file => {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
  };

  const render = () => {
    const file = input.files && input.files[0];
    views.forEach(({ root, idle, standalone }) => {
      if (!file) {
        root.dataset.state = 'idle';
        root.innerHTML = idle;
        if (standalone) {
          root.setAttribute('role', 'button');
          root.setAttribute('tabindex', '0');
        }
        return;
      }
      root.dataset.state = 'filled';
      // Com o arquivo escolhido a caixa contem o botao Remover: deixa de ser
      // um controle unico para nao aninhar dois alvos de teclado.
      if (standalone) {
        root.removeAttribute('role');
        root.removeAttribute('tabindex');
      }
      root.innerHTML = `
        <span class="icon-tile" aria-hidden="true">${CHECK_ICON}</span>
        <span class="file-chip-body">
          <span class="file-chip-name"></span>
          <span class="file-chip-meta"></span>
        </span>
        <button class="button button-ghost" type="button" data-remove>Remover</button>`;
      root.querySelector('.file-chip-name').textContent = file.name;
      root.querySelector('.file-chip-meta').textContent = `${formatSize(file.size)} · toque para trocar`;
    });
    onChange?.(file || null);
  };

  views.forEach(({ root }) => {
    root.addEventListener('click', event => {
      if (event.target.closest('[data-remove]')) {
        event.stopPropagation();
        clear();
        return;
      }
      openPicker();
    });

    if (root.getAttribute('role') === 'button') {
      root.addEventListener('keydown', event => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        event.preventDefault();
        openPicker();
      });
    }

    ['dragenter', 'dragover'].forEach(type => root.addEventListener(type, event => {
      event.preventDefault();
      root.dataset.dragover = 'true';
    }));
    ['dragleave', 'dragend', 'drop'].forEach(type => root.addEventListener(type, () => {
      delete root.dataset.dragover;
    }));
    root.addEventListener('drop', event => {
      event.preventDefault();
      const file = event.dataTransfer?.files?.[0];
      if (file && accepts(input, file)) assign(file);
    });
  });

  input.addEventListener('change', render);
  render();
  return { clear, render, openPicker };
}
