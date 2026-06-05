from __future__ import annotations

from datetime import UTC, datetime


class OperationalMetadataClient:
    """Monta registros padronizados para auditoria operacional das DAGs."""

    def build_execution_record(
        self,
        *,
        execution_id: str,
        document_id: str,
        dag_name: str,
        status_execucao: str,
        versao_pipeline: str = "local-dev",
        versao_contrato: str | None = None,
        versao_layout_signature: str | None = None,
        fallback_acionado: bool = False,
    ) -> dict[str, object]:
        """Cria um registro de execucao com campos comuns do pipeline."""
        return {
            "execution_id": execution_id,
            "document_id": document_id,
            "dag_origem": dag_name,
            "versao_pipeline": versao_pipeline,
            "versao_contrato": versao_contrato,
            "versao_layout_signature": versao_layout_signature,
            "status_execucao": status_execucao,
            "fallback_acionado": fallback_acionado,
            "iniciado_em": datetime.now(UTC).isoformat(),
        }

    def build_artifact_record(
        self,
        *,
        execution_id: str,
        tipo_artefato: str,
        bucket_name: str,
        object_key: str,
    ) -> dict[str, str]:
        """Cria um registro de artefato apontando para objeto no data lake."""
        return {
            "execution_id": execution_id,
            "tipo_artefato": tipo_artefato,
            "bucket_name": bucket_name,
            "object_key": object_key,
        }


OPERATIONAL_METADATA_CLIENT = OperationalMetadataClient()
