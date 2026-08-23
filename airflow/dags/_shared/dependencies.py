"""Fábricas explícitas de dependências para as DAGs do Airflow.

Este é o único ponto da camada Airflow que conhece os adaptadores concretos.
Os casos de uso continuam importáveis e testáveis sem Airflow.
"""

from functools import lru_cache

from document_intelligence.application.use_cases.documents import SourceDocumentProcessingUseCase
from document_intelligence.application.use_cases.fallback import FallbackLlmService
from document_intelligence.application.use_cases.resolution import ResolveSchemaUseCase
from document_intelligence.application.use_cases.runtime_payloads import ConstrutorasPayloadBuilder
from document_intelligence.infrastructure.docling import DoclingPipelineClient
from document_intelligence.infrastructure.governance import OperationalMetadataClient
from document_intelligence.infrastructure.llm import FallbackLlmClient, HttpClient
from document_intelligence.infrastructure.ri.ri_results_gateway import RiResultsClient
from document_intelligence.infrastructure.storage import MinioStorageClient
from document_intelligence.shared.config import (
    PROJECT_PATHS,
    LocalPlatformConfig,
    RuntimeConfigLoader,
)


@lru_cache(maxsize=1)
def _settings() -> tuple[RuntimeConfigLoader, LocalPlatformConfig]:
    loader = RuntimeConfigLoader()
    return loader, loader.load_local_platform_config()


@lru_cache(maxsize=1)
def build_source_document_processing_use_case() -> SourceDocumentProcessingUseCase:
    """Monta o caso de uso da DAG 1 com adaptadores concretos explícitos."""
    loader, config = _settings()
    http_client = HttpClient()
    return SourceDocumentProcessingUseCase(
        config=config,
        config_loader=loader,
        http_client=http_client,
        ri_client=RiResultsClient(http_client=http_client),
        minio_client=MinioStorageClient(config),
        docling_client=DoclingPipelineClient(
            config_loader=loader,
            http_client=http_client,
        ),
    )


@lru_cache(maxsize=1)
def build_resolution_use_case() -> ResolveSchemaUseCase:
    """Monta o caso de uso da DAG 2 com o repositório MinIO explícito."""
    loader, config = _settings()
    return ResolveSchemaUseCase(
        config_loader=loader,
        project_paths=PROJECT_PATHS,
        minio_client=MinioStorageClient(config),
    )


@lru_cache(maxsize=1)
def build_construtoras_payload_builder() -> ConstrutorasPayloadBuilder:
    """Monta o gerador de runtime legado da DAG 2 sem importar plugins."""
    loader, _config = _settings()
    return ConstrutorasPayloadBuilder(
        config_loader=loader,
        project_paths=PROJECT_PATHS,
        docling_client=DoclingPipelineClient(config_loader=loader),
        metadata_client=OperationalMetadataClient(),
    )


@lru_cache(maxsize=1)
def build_fallback_llm_service() -> FallbackLlmService:
    """Monta o caso de uso da DAG 3 com clientes concretos explícitos."""
    loader, config = _settings()
    http_client = HttpClient()
    return FallbackLlmService(
        config_loader=loader,
        minio_client=MinioStorageClient(config),
        llm_client=FallbackLlmClient(
            config_loader=loader,
            http_client=http_client,
        ),
    )
