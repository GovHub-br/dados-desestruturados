from __future__ import annotations

import re
import uuid
from typing import Any, Iterable, Optional

TITLE_LABEL_HINTS = {
    "title",
    "document_title",
    "section_header",
    "section_header_level_1",
    "section_header_level_2",
    "section_header_level_3",
    "header",
}

TITLE_PREFIX_HINTS = (
    "comparativo",
    "resumo",
    "lancamentos",
    "lançamentos",
    "acumulado",
    "indicadores",
    "overview",
    "summary",
    "analysis",
    "appendix",
    "section",
)

UNIT_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"R\$", re.I), "currency_brl"),
    (re.compile(r"\b(?:bi|billion)\b", re.I), "billions"),
    (re.compile(r"\b(?:mi|million)\b", re.I), "millions"),
    (re.compile(r"%"), "percent"),
]


def stable_id(*parts: Any) -> str:
    material = "||".join(str(p) for p in parts if p is not None)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, material))


def slugify(text: str) -> str:
    text = text.strip().lower()
    replacements = {
        "á": "a",
        "à": "a",
        "ã": "a",
        "â": "a",
        "ä": "a",
        "é": "e",
        "ê": "e",
        "ë": "e",
        "í": "i",
        "ï": "i",
        "ó": "o",
        "ô": "o",
        "õ": "o",
        "ö": "o",
        "ú": "u",
        "ü": "u",
        "ç": "c",
        "/": "_",
        "-": "_",
        " ": "_",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"[^a-z0-9_]+", "", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "untitled"


def normalize_space(text: Optional[str]) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def infer_unit_hint(text: str) -> Optional[str]:
    for pattern, unit in UNIT_PATTERNS:
        if pattern.search(text):
            return unit
    return None


def looks_like_title(text: str, label: str) -> bool:
    normalized = normalize_space(text)
    if not normalized:
        return False
    if label in TITLE_LABEL_HINTS:
        return True
    lowered = normalized.lower()
    if len(normalized) <= 140 and any(lowered.startswith(prefix) for prefix in TITLE_PREFIX_HINTS):
        return True
    if len(normalized) <= 120 and (normalized.isupper() or normalized.istitle()) and len(normalized.split()) <= 14:
        return True
    return False


def normalize_columns(columns: Iterable[Any]) -> list[str]:
    out: list[str] = []
    used: dict[str, int] = {}
    for idx, value in enumerate(columns):
        base = slugify(normalize_space(str(value)) or f"column_{idx + 1}")
        used[base] = used.get(base, 0) + 1
        out.append(base if used[base] == 1 else f"{base}_{used[base]}")
    return out
