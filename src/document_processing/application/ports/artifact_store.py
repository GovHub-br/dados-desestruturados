"""Porta mínima para persistência de artefatos JSON.

Casos de uso dependem desta interface, não do cliente MinIO. A implementação
concreta será migrada na fase de infraestrutura da reorganização.
"""

from __future__ import annotations

from typing import Any, Protocol


class JsonArtifactStore(Protocol):
    """Lê e grava artefatos JSON identificados por chave lógica."""

    def read_json(self, key: str) -> dict[str, Any]:
        """Retorna o objeto JSON persistido em ``key``."""

    def write_json(self, key: str, payload: dict[str, Any]) -> None:
        """Persiste ``payload`` em ``key``."""

