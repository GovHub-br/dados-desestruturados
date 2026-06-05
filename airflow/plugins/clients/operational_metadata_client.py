from __future__ import annotations

from datetime import UTC, datetime


def build_execution_record(
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
    *,
    execution_id: str,
    tipo_artefato: str,
    bucket_name: str,
    object_key: str,
) -> dict[str, str]:
    return {
        "execution_id": execution_id,
        "tipo_artefato": tipo_artefato,
        "bucket_name": bucket_name,
        "object_key": object_key,
    }
