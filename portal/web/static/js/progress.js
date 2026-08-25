// Barra de progresso do envio: 1:1 com o upload enquanto ele acontece.

export function createProgress(root, bar, label) {
  const setVisible = visible => {
    root.dataset.visible = String(visible);
    root.setAttribute('aria-hidden', String(!visible));
  };

  return {
    start(text) {
      setVisible(true);
      root.dataset.indeterminate = 'false';
      bar.style.width = '0%';
      label.textContent = text;
    },
    set(ratio) {
      if (ratio === null) {
        root.dataset.indeterminate = 'true';
        return;
      }
      root.dataset.indeterminate = 'false';
      const percent = Math.round(ratio * 100);
      bar.style.width = `${percent}%`;
      label.textContent = percent >= 100
        ? 'Arquivo recebido. Preparando a execução…'
        : `Enviando arquivo… ${percent}%`;
    },
    waiting(text) {
      root.dataset.indeterminate = 'true';
      label.textContent = text;
    },
    done() {
      setVisible(false);
      root.dataset.indeterminate = 'false';
      bar.style.width = '0%';
      label.textContent = '';
    },
  };
}
