"""Normalização de números independente do pipeline Docling."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

THOUSANDS_INTEGER_RE = re.compile(r"[-+]?\d{1,3}(?:\.\d{3})+")
# Razao publicada como "numero de vezes": "3,49x", "0,69x", "1.5X".
RATIO_SUFFIX_RE = re.compile(r"^[-+]?[\d.,]+\s*[xX]$")


def parse_flexible_number(value: Any, *, column_name: str | None = None) -> float | None:
    """Converte uma célula publicada em número sem depender de extrator externo."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = _normalize_space(str(value)).replace("\u00a0", " ")
    if not text:
        return None

    # Parenteses sao o sinal, nao decoracao: "(50,4)" e prejuizo. Tratado antes
    # do percentual para valer nos dois caminhos, e reaplicado sobre a
    # magnitude ja normalizada em cada saida.
    text, negative = _strip_accounting_negative(text)
    # O "x" de razao e marcador de unidade; sai antes da varredura de palavras,
    # que rejeita qualquer token alfabetico fora da lista de multiplicadores.
    if RATIO_SUFFIX_RE.match(text):
        text = text[:-1].strip()

    percent = _parse_percent(text)
    if percent is not None:
        return -percent if negative else percent

    scrubbed = text.replace("R$", " ")
    words = re.findall(r"[A-Za-zÀ-ÿ]+", scrubbed)
    if any(token.lower() not in {"bi", "billion", "mi", "million", "mil"} for token in words):
        return None

    column = _normalize_space(column_name or "").lower()
    prefers_integer = bool(re.fullmatch(r"\d+t_\d{4}", column)) or any(
        hint in column
        for hint in ("unidades", "total", "acumulado", "4t_", "3t_", "2t_", "1t_", "norte", "nordeste", "sudeste", "sul", "centro_oeste")
    )
    prefers_percent = any(hint in column for hint in ("percent", "variacao", "variação", "pct"))

    integer = _parse_integer_thousands(text)
    if integer is not None and prefers_integer:
        return -integer if negative else integer

    multiplier = 1.0
    if re.search(r"\b(?:bi|billion)\b", text, re.I):
        multiplier = 1_000_000_000.0
    elif re.search(r"\b(?:mi|million)\b", text, re.I):
        multiplier = 1_000_000.0
    elif re.search(r"\bmil\b", text, re.I):
        multiplier = 1_000.0

    cleaned = re.sub(r"[^0-9,.-]", "", text)
    if not cleaned:
        return None
    if prefers_integer and THOUSANDS_INTEGER_RE.fullmatch(cleaned):
        cleaned = cleaned.replace(".", "")
    elif "," in cleaned and "." in cleaned:
        cleaned = (
            cleaned.replace(".", "").replace(",", ".")
            if cleaned.rfind(",") > cleaned.rfind(".")
            else cleaned.replace(",", "")
        )
    elif "," in cleaned:
        cleaned = (
            cleaned.replace(".", "").replace(",", ".")
            if prefers_percent or (cleaned.count(",") == 1 and len(cleaned.split(",")[-1]) in {1, 2})
            else cleaned.replace(",", "")
        )
    elif THOUSANDS_INTEGER_RE.fullmatch(cleaned) or cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "")
    try:
        magnitude = float(cleaned) * multiplier
    except ValueError:
        return None
    return -magnitude if negative else magnitude


def _strip_accounting_negative(value: str) -> tuple[str, bool]:
    """Separa o sinal contabil entre parenteses do conteudo da celula.

    Devolve ``(texto, True)`` quando a celula inteira esta entre parenteses e
    contem algum digito — "(50,4)", "(794.123)", "(3,1%)". Um texto sem digito
    ("(vazio)") nao e numero e volta intacto, para ser rejeitado adiante.
    """
    inner = value.strip()
    if len(inner) >= 2 and inner.startswith("(") and inner.endswith(")"):
        stripped = inner[1:-1].strip()
        if stripped and re.search(r"\d", stripped):
            return stripped, True
    return value, False


def _parse_integer_thousands(value: str) -> float | None:
    cleaned = re.sub(r"[^\d.\-+]", "", value)
    if THOUSANDS_INTEGER_RE.fullmatch(cleaned):
        return float(cleaned.replace(".", ""))
    if re.fullmatch(r"[-+]?\d+", cleaned):
        return float(cleaned)
    return None


def _parse_percent(value: str) -> float | None:
    if "%" not in value:
        return None
    cleaned = re.sub(r"[^0-9,\.\-+]", "", value)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        cleaned = (
            cleaned.replace(".", "").replace(",", ".")
            if cleaned.rfind(",") > cleaned.rfind(".")
            else cleaned.replace(",", "")
        )
    elif "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_space(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", normalized).strip()
