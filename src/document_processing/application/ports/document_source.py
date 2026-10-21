"""Porta mínima para fontes externas que publicam documentos periodicamente."""

from __future__ import annotations

from typing import Any, Protocol


class DocumentSource(Protocol):
    """Consulta uma fonte e informa quais documentos ela publica hoje."""

    def detect_candidates(self) -> list[dict[str, Any]]:
        """Retorna os documentos publicados, já no formato de candidato de origem.

        Cada candidato traz ao menos ``domain``, ``entity_slug``, ``entity_name``,
        ``company_slug``, ``company_name``, ``title``, ``url``, ``provider``,
        ``source_url``, ``period_label``, ``reference_year`` e ``reference_quarter``.
        A fonte não decide o que é novo: isso depende do que já existe no MinIO.
        """
