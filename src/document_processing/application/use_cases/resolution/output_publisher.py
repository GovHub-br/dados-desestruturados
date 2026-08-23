"""Persistência dos artefatos finais de uma resolução determinística."""

from __future__ import annotations

from typing import Any

from document_processing.infrastructure.storage import MinioStorageClient


class ResolutionOutputPublisher:
    """Publica somente os três artefatos estáveis da DAG 2."""

    def __init__(self, artifact_store: MinioStorageClient) -> None:
        self.artifact_store = artifact_store

    def persist(
        self,
        *,
        loaded: dict[str, Any],
        validation: dict[str, Any],
        resolved: dict[str, Any],
        audit: dict[str, Any],
    ) -> dict[str, str]:
        keys = self._output_keys(loaded)
        validation["tipo_artefato"] = "validacao_layout_signature"
        audit["tipo_artefato"] = "auditoria_resolucao"
        return {
            "validacao_layout_signature_uri": self.artifact_store.put_json(
                object_key=keys["validacao_layout_signature"], payload=validation
            ),
            "schema_saida_resolvido_uri": self.artifact_store.put_json(
                object_key=keys["schema_saida_resolvido"],
                payload=resolved.get("schema_saida", {}),
            ),
            "auditoria_resolucao_uri": self.artifact_store.put_json(
                object_key=keys["auditoria_resolucao"], payload=audit
            ),
        }

    @staticmethod
    def _output_keys(loaded: dict[str, Any]) -> dict[str, str]:
        configured = loaded.get("output_keys")
        if isinstance(configured, dict):
            return {name: str(configured[name]) for name in (
                "validacao_layout_signature",
                "schema_saida_resolvido",
                "auditoria_resolucao",
            )}

        runtime = loaded["runtime"]
        by_type = {
            str(item.get("tipo_artefato")): str(item.get("object_key"))
            for item in runtime.get("artifacts", [])
        }
        keys = {
            "validacao_layout_signature": by_type.get("validacao_layout_signature", ""),
            "schema_saida_resolvido": by_type.get("schema_saida_resolvido", ""),
            "auditoria_resolucao": by_type.get("auditoria_resolucao", ""),
        }
        if not all(keys.values()):
            raise RuntimeError("Runtime da DAG 2 sem object_key esperado para persistencia.")
        return keys
