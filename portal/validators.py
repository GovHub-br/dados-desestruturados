"""Validacoes compartilhadas pelos servicos do portal."""

from __future__ import annotations

import re

from fastapi import HTTPException

SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SEMVER_PATTERN = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")


def slug(value: str, field: str) -> str:
    cleaned = value.strip().lower()
    if not SLUG_PATTERN.fullmatch(cleaned):
        raise HTTPException(status_code=422, detail=f"{field} deve ser um slug minusculo valido.")
    return cleaned


def safe_filename(value: str, *, fallback: str) -> str:
    cleaned = FILENAME_PATTERN.sub("_", value).strip("._")
    return cleaned or fallback
