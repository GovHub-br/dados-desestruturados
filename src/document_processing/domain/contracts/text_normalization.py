"""Normalizacao de texto compartilhada por resolucao, selecao e avaliacao.

Uma unica funcao para comparar rotulos do documento com sinonimos do contrato,
sem que cada etapa carregue a sua propria variante.
"""

from __future__ import annotations

import re
import unicodedata


def normalize_text(value: object) -> str:
    """ASCII, minusculas e espacos colapsados; vazio para valores nulos."""
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKD", str(value))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", ascii_value).strip().lower()
