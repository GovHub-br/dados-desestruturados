"""Protecao de bootstrap das rotas de API."""

from __future__ import annotations

from fastapi import Header, HTTPException

from . import config


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Producao deve substituir isto pela integracao com o provedor corporativo."""
    expected = config.api_token()
    if expected and authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="Token do portal ausente ou invalido.")
