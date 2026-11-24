"""Identidade legivel de novos documentos e reconhecimento de caminhos legados."""

from __future__ import annotations

import re
from datetime import UTC, datetime


def new_document_id(digest: str) -> str:
    """Data de primeira entrada em UTC, seguida do identificador de conteudo."""
    return f"{datetime.now(UTC):%Y-%m-%d_%H-%M-%SZ}__{digest[:32]}"


def document_id_from_key(key: str, digest: str) -> str:
    match = re.search(r"/document_id=([^/]+)/", key)
    return match.group(1) if match else digest[:32]


def find_pdf_by_digest(keys: list[str], digest: str) -> str | None:
    """Reconhece tanto IDs antigos como PDFs em diretorios com data de entrada."""
    for key in sorted(keys):
        filename = key.rsplit("/", 1)[-1]
        if filename.startswith(f"{digest[:16]}_") or f"/document_id={digest[:32]}/" in key:
            return key
    return None
