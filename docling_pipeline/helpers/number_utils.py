from __future__ import annotations

import re
from typing import Any, Optional

from .text_utils import normalize_space


THOUSANDS_INTEGER_RE = re.compile(r"[-+]?\d{1,3}(?:\.\d{3})+")
PERCENT_COLUMN_HINTS = ("percent", "variacao", "variação", "pct")
INTEGER_COLUMN_HINTS = (
    "unidades",
    "total",
    "acumulado",
    "4t_",
    "3t_",
    "2t_",
    "1t_",
    "norte",
    "nordeste",
    "sudeste",
    "sul",
    "centro_oeste",
)


def _normalize_numeric_text(text: str) -> str:
    return normalize_space(text).replace("\u00a0", " ")


def _column_prefers_percent(column_name: Optional[str]) -> bool:
    lowered = (column_name or "").lower()
    return any(hint in lowered for hint in PERCENT_COLUMN_HINTS)


def _column_prefers_integer(column_name: Optional[str]) -> bool:
    lowered = (column_name or "").lower()
    return bool(re.fullmatch(r"\d+t_\d{4}", lowered)) or any(hint in lowered for hint in INTEGER_COLUMN_HINTS)


def parse_ptbr_integer_thousands(value: Any) -> Optional[float]:
    text = _normalize_numeric_text(str(value))
    cleaned = re.sub(r"[^\d.\-+]", "", text)
    if not cleaned:
        return None
    if THOUSANDS_INTEGER_RE.fullmatch(cleaned):
        return float(cleaned.replace(".", ""))
    if re.fullmatch(r"[-+]?\d+", cleaned):
        return float(cleaned)
    return None


def parse_ptbr_percent(value: Any) -> Optional[float]:
    text = _normalize_numeric_text(str(value))
    if "%" not in text:
        return None
    cleaned = re.sub(r"[^0-9,\.\-+]", "", text)
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_flexible_number(value: Any, *, column_name: Optional[str] = None) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = _normalize_numeric_text(str(value))
    if not text:
        return None

    if parse_ptbr_percent(text) is not None:
        return parse_ptbr_percent(text)

    # Reject labels and mixed semantic tokens such as "4T 2025" or "Dez 2025".
    scrubbed = text.replace("R$", " ")
    word_tokens = re.findall(r"[A-Za-zÀ-ÿ]+", scrubbed)
    allowed_word_tokens = {"bi", "billion", "mi", "million", "mil"}
    if any(token.lower() not in allowed_word_tokens for token in word_tokens):
        return None

    integer_value = parse_ptbr_integer_thousands(text)
    if integer_value is not None and _column_prefers_integer(column_name):
        return integer_value

    working = text.strip()
    multiplier = 1.0

    if re.search(r"\b(?:bi|billion)\b", working, re.I):
        multiplier = 1_000_000_000.0
    elif re.search(r"\b(?:mi|million)\b", working, re.I):
        multiplier = 1_000_000.0
    elif re.search(r"\bmil\b", working, re.I):
        multiplier = 1_000.0
    elif re.search(r"%", working):
        multiplier = 1.0

    cleaned = re.sub(r"[^0-9,.-]", "", working)
    if not cleaned:
        return None

    # Heuristics for pt-BR and en-US style numbers.
    if _column_prefers_integer(column_name) and THOUSANDS_INTEGER_RE.fullmatch(cleaned):
        cleaned = cleaned.replace(".", "")
    elif "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        if _column_prefers_percent(column_name):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        elif cleaned.count(",") == 1 and len(cleaned.split(",")[-1]) in {1, 2}:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        if THOUSANDS_INTEGER_RE.fullmatch(cleaned):
            cleaned = cleaned.replace(".", "")
        elif cleaned.count(".") > 1:
            cleaned = cleaned.replace(".", "")

    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def maybe_metric_from_text(text: str) -> Optional[tuple[str, Optional[float], Optional[str]]]:
    compact = normalize_space(text)
    if not compact or len(compact) > 80:
        return None

    if re.fullmatch(r"[\d\s/.,-]+", compact):
        return None

    number_matches = list(re.finditer(r"(?:R\$\s*)?[-+]?\d[\d.,]*(?:\s*(?:bi|mi|mil|%))?", compact, flags=re.I))
    if not number_matches:
        return None

    last = number_matches[-1]
    value_text = last.group(0).strip()
    value_numeric = parse_flexible_number(value_text)
    if value_numeric is None:
        return None

    label_part = normalize_space((compact[: last.start()] + compact[last.end() :]).strip(" :-|"))
    if not label_part:
        return None

    return label_part, value_numeric, value_text
