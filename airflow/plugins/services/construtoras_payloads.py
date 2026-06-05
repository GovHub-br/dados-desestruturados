from __future__ import annotations

from datetime import UTC, datetime

from helpers import load_local_platform_config, project_path
from plugins.clients import (
    build_artifact_record,
    build_execution_record,
    render_extract_command,
)


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _execution_id(prefix: str) -> str:
    return f"{prefix}__{_timestamp()}"


def _document_id(entidade: str) -> str:
    return f"{entidade}__documento_exemplo"


def build_extract_runtime() -> dict[str, object]:
    config = load_local_platform_config()
    execution_id = _execution_id("dag_detecta_pdf_e_extrai")
    document_id = _document_id(config.entidade)
    extraction_prefix = (
        f"{config.minio_execution_prefix}/{config.entidade}/"
        f"document_id={document_id}/execution_id={execution_id}/extraction"
    )

    command = render_extract_command(
        input_path=project_path("pdfs_testes", "dados.pdf"),
        output_dir=project_path("tmp", execution_id),
    )

    return {
        "dag_name": "dag_detecta_pdf_e_extrai",
        "execution": build_execution_record(
            execution_id=execution_id,
            document_id=document_id,
            dag_name="dag_detecta_pdf_e_extrai",
            status_execucao="planejada",
        ),
        "planned_command": command,
        "artifacts": [
            build_artifact_record(
                execution_id=execution_id,
                tipo_artefato="pasta_extracao",
                bucket_name=config.minio_bucket,
                object_key=extraction_prefix,
            ),
        ],
    }


def build_resolution_runtime() -> dict[str, object]:
    config = load_local_platform_config()
    execution_id = _execution_id("dag_resolve_schema_saida")
    document_id = _document_id(config.entidade)
    resolution_prefix = (
        f"{config.minio_execution_prefix}/{config.entidade}/"
        f"document_id={document_id}/execution_id={execution_id}/resolution"
    )

    return {
        "dag_name": "dag_resolve_schema_saida",
        "execution": build_execution_record(
            execution_id=execution_id,
            document_id=document_id,
            dag_name="dag_resolve_schema_saida",
            status_execucao="planejada",
            versao_contrato="1.2.0",
            versao_layout_signature="4.0.0",
        ),
        "inputs": {
            "contrato_semantico": (
                f"minio://{config.minio_bucket}/"
                f"{config.minio_contract_prefix}/v1.2.0/contrato_semantico_construtora.json"
            ),
            "layout_signature": (
                f"minio://{config.minio_bucket}/"
                f"{config.minio_layout_prefix}/{config.entidade}/v4.0.0/layout_signature_deterministico.json"
            ),
        },
        "artifacts": [
            build_artifact_record(
                execution_id=execution_id,
                tipo_artefato="validacao_layout_signature",
                bucket_name=config.minio_bucket,
                object_key=f"{resolution_prefix}/validacao_layout_signature.json",
            ),
            build_artifact_record(
                execution_id=execution_id,
                tipo_artefato="schema_saida_resolvido",
                bucket_name=config.minio_bucket,
                object_key=f"{resolution_prefix}/schema_saida_resolvido.json",
            ),
            build_artifact_record(
                execution_id=execution_id,
                tipo_artefato="auditoria_resolucao",
                bucket_name=config.minio_bucket,
                object_key=f"{resolution_prefix}/auditoria_resolucao.json",
            ),
        ],
    }


def build_fallback_runtime() -> dict[str, object]:
    config = load_local_platform_config()
    execution_id = _execution_id("dag_valida_e_fallback_llm")
    document_id = _document_id(config.entidade)
    fallback_prefix = (
        f"fallback/{config.dominio}/{config.entidade}/"
        f"document_id={document_id}/execution_id={execution_id}"
    )

    return {
        "dag_name": "dag_valida_e_fallback_llm",
        "execution": build_execution_record(
            execution_id=execution_id,
            document_id=document_id,
            dag_name="dag_valida_e_fallback_llm",
            status_execucao="planejada",
            versao_contrato="1.2.0",
            versao_layout_signature="4.0.0",
            fallback_acionado=True,
        ),
        "policy": {
            "mode": "fallback_assistido",
            "regenerar_apenas_campos_quebrados": True,
            "regenerar_mapeamento_inteiro_apenas_em_quebra_ampla": True,
        },
        "artifacts": [
            build_artifact_record(
                execution_id=execution_id,
                tipo_artefato="proposta_novo_mapeamento",
                bucket_name=config.minio_bucket,
                object_key=f"{fallback_prefix}/proposta_novo_mapeamento.json",
            ),
            build_artifact_record(
                execution_id=execution_id,
                tipo_artefato="analise_semantica_llm",
                bucket_name=config.minio_bucket,
                object_key=f"{fallback_prefix}/analise_semantica_llm.json",
            ),
        ],
    }


def build_bronze_runtime() -> dict[str, object]:
    config = load_local_platform_config()
    execution_id = _execution_id("dag_ingere_bronze")
    document_id = _document_id(config.entidade)

    return {
        "dag_name": "dag_ingere_bronze",
        "execution": build_execution_record(
            execution_id=execution_id,
            document_id=document_id,
            dag_name="dag_ingere_bronze",
            status_execucao="planejada",
        ),
        "destination": {
            "schema": "bronze",
            "table_hint": "balancos_construtoras",
        },
        "source": {
            "schema_saida_resolvido": (
                f"minio://{config.minio_bucket}/"
                f"{config.minio_execution_prefix}/{config.entidade}/"
                f"document_id={document_id}/execution_id={execution_id}/resolution/schema_saida_resolvido.json"
            ),
        },
    }
