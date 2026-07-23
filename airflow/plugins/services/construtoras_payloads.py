from __future__ import annotations

from datetime import UTC, datetime

from helpers import PROJECT_PATHS, RUNTIME_CONFIG_LOADER, ProjectPaths, RuntimeConfigLoader
from plugins.clients import (
    DOCLING_PIPELINE_CLIENT,
    OPERATIONAL_METADATA_CLIENT,
    DoclingPipelineClient,
    OperationalMetadataClient,
)


class ConstrutorasPayloadBuilder:
    """Monta payloads planejados para as DAGs do dominio de construtoras."""

    def __init__(
        self,
        *,
        config_loader: RuntimeConfigLoader | None = None,
        project_paths: ProjectPaths | None = None,
        docling_client: DoclingPipelineClient | None = None,
        metadata_client: OperationalMetadataClient | None = None,
    ) -> None:
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self.project_paths = project_paths or PROJECT_PATHS
        self.docling_client = docling_client or DOCLING_PIPELINE_CLIENT
        self.metadata_client = metadata_client or OPERATIONAL_METADATA_CLIENT

    def build_extract_runtime(self) -> dict[str, object]:
        """Monta o payload planejado da DAG de deteccao e extracao."""
        config = self.config_loader.load_local_platform_config()
        execution_id = self._execution_id("dag_detecta_pdf_e_extrai")
        document_id = self._document_id(config.entidade)
        extraction_prefix = (
            f"{config.minio_extract_prefix}/{config.entidade}/"
            f"document_id={document_id}/execution_id={execution_id}/extraction"
        )

        command = self.docling_client.render_extract_command(
            input_path=self.project_paths.path("pdfs_testes", "dados.pdf"),
            output_dir=self.project_paths.path("tmp", execution_id),
        )

        return {
            "dag_name": "dag_detecta_pdf_e_extrai",
            "execution": self.metadata_client.build_execution_record(
                execution_id=execution_id,
                document_id=document_id,
                dag_name="dag_detecta_pdf_e_extrai",
                status_execucao="planejada",
            ),
            "planned_command": command,
            "artifacts": [
                self.metadata_client.build_artifact_record(
                    execution_id=execution_id,
                    tipo_artefato="pasta_extracao",
                    bucket_name=config.minio_bucket,
                    object_key=extraction_prefix,
                ),
            ],
        }

    def build_resolution_runtime(self) -> dict[str, object]:
        """Monta o payload planejado da DAG de resolucao de schema."""
        config = self.config_loader.load_local_platform_config()
        execution_id = self._execution_id("dag_resolve_schema_saida")
        document_id = self._document_id(config.entidade)
        resolution_prefix = (
            f"{config.minio_resolution_prefix}/{config.entidade}/"
            f"document_id={document_id}/execution_id={execution_id}/resolution"
        )

        return {
            "dag_name": "dag_resolve_schema_saida",
            "execution": self.metadata_client.build_execution_record(
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
                    f"{config.minio_contract_prefix}/v1.3.0/contrato_semantico_construtora.json"
                ),
                "layout_signature": (
                    f"minio://{config.minio_bucket}/"
                    f"{config.minio_layout_prefix}/{config.entidade}/v4.0.0/layout_signature_deterministico.json"
                ),
            },
            "artifacts": [
                self.metadata_client.build_artifact_record(
                    execution_id=execution_id,
                    tipo_artefato="validacao_layout_signature",
                    bucket_name=config.minio_bucket,
                    object_key=f"{resolution_prefix}/validacao_layout_signature.json",
                ),
                self.metadata_client.build_artifact_record(
                    execution_id=execution_id,
                    tipo_artefato="schema_saida_resolvido",
                    bucket_name=config.minio_bucket,
                    object_key=f"{resolution_prefix}/schema_saida_resolvido.json",
                ),
                self.metadata_client.build_artifact_record(
                    execution_id=execution_id,
                    tipo_artefato="auditoria_resolucao",
                    bucket_name=config.minio_bucket,
                    object_key=f"{resolution_prefix}/auditoria_resolucao.json",
                ),
            ],
        }

    def build_fallback_runtime(self) -> dict[str, object]:
        """Monta o payload planejado da DAG de fallback assistido por LLM."""
        config = self.config_loader.load_local_platform_config()
        execution_id = self._execution_id("dag_valida_e_fallback_llm")
        document_id = self._document_id(config.entidade)
        fallback_prefix = (
            f"fallback/{config.dominio}/{config.entidade}/"
            f"document_id={document_id}/execution_id={execution_id}"
        )

        return {
            "dag_name": "dag_valida_e_fallback_llm",
            "execution": self.metadata_client.build_execution_record(
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
                self.metadata_client.build_artifact_record(
                    execution_id=execution_id,
                    tipo_artefato="layout_signature_candidato",
                    bucket_name=config.minio_bucket,
                    object_key=f"{fallback_prefix}/layout_signature_candidato.json",
                ),
                self.metadata_client.build_artifact_record(
                    execution_id=execution_id,
                    tipo_artefato="resultado_revalidacao_candidato",
                    bucket_name=config.minio_bucket,
                    object_key=f"{fallback_prefix}/revalidation/resultado_revalidacao_candidato.json",
                ),
                self.metadata_client.build_artifact_record(
                    execution_id=execution_id,
                    tipo_artefato="publicacao_layout_signature",
                    bucket_name=config.minio_bucket,
                    object_key=f"{fallback_prefix}/publicacao_layout_signature.json",
                ),
            ],
        }

    def build_bronze_runtime(self) -> dict[str, object]:
        """Monta o payload planejado da DAG de ingestao bronze."""
        config = self.config_loader.load_local_platform_config()
        execution_id = self._execution_id("dag_ingere_bronze")
        document_id = self._document_id(config.entidade)

        return {
            "dag_name": "dag_ingere_bronze",
            "execution": self.metadata_client.build_execution_record(
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
                    f"{config.minio_resolution_prefix}/{config.entidade}/"
                    f"document_id={document_id}/execution_id={execution_id}/resolution/schema_saida_resolvido.json"
                ),
            },
        }

    @staticmethod
    def _timestamp() -> str:
        """Gera timestamp UTC compacto para ids de execucao."""
        return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    def _execution_id(self, prefix: str) -> str:
        """Deriva um id de execucao legivel a partir do nome da DAG."""
        return f"{prefix}__{self._timestamp()}"

    @staticmethod
    def _document_id(entidade: str) -> str:
        """Gera um document_id placeholder usado no planejamento das DAGs."""
        return f"{entidade}__documento_exemplo"


CONSTRUTORAS_PAYLOAD_BUILDER = ConstrutorasPayloadBuilder()
