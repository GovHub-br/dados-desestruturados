from __future__ import annotations

import hashlib
import logging
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from document_intelligence.infrastructure.docling.docling_gateway import (
    DOCLING_PIPELINE_CLIENT,
    DoclingPipelineClient,
)
from document_intelligence.infrastructure.llm.http_client import HTTP_CLIENT, HttpClient
from document_intelligence.infrastructure.ri.ri_results_gateway import (
    DisclosureWindow,
    RI_RESULTS_CLIENT,
    RiResultsClient,
)
from document_intelligence.infrastructure.storage.minio_artifact_repository import MinioStorageClient
from document_intelligence.infrastructure.storage.semantic_contract_registry import SemanticContractRegistry
from document_intelligence.shared.config.runtime import (
    LocalPlatformConfig,
    RUNTIME_CONFIG_LOADER,
    RuntimeConfigLoader,
)
from .constants import DAG_NAME
from .origin_document_extraction import OriginDocumentExtractionMixin
from .origin_document_storage import OriginDocumentStorageMixin


class SourceDocumentProcessingUseCase(
    OriginDocumentExtractionMixin,
    OriginDocumentStorageMixin,
):
    """Coordena descoberta, persistência e extração de documentos de origem."""

    def __init__(
        self,
        *,
        config: LocalPlatformConfig | None = None,
        config_loader: RuntimeConfigLoader | None = None,
        http_client: HttpClient | None = None,
        ri_client: RiResultsClient | None = None,
        minio_client: MinioStorageClient | None = None,
        docling_client: DoclingPipelineClient | None = None,
    ) -> None:
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self._config = config
        self.http_client = http_client or HTTP_CLIENT
        self.ri_client = ri_client or RI_RESULTS_CLIENT
        self._minio_client = minio_client
        self.docling_client = docling_client or DOCLING_PIPELINE_CLIENT

    @property
    def config(self) -> LocalPlatformConfig:
        """Carrega a configuracao apenas quando a DAG realmente precisar dela."""
        if self._config is None:
            self._config = self.config_loader.load_local_platform_config()
        return self._config

    @property
    def minio_client(self) -> MinioStorageClient:
        """Instancia o client MinIO sob demanda usando a configuracao resolvida."""
        if self._minio_client is None:
            self._minio_client = MinioStorageClient(self.config)
        return self._minio_client

    def build_detection_context(self, today: date | None = None) -> dict[str, Any]:
        """Monta o contexto de execucao com a janela trimestral que deve ser monitorada."""
        window = self.ri_client.current_disclosure_window(today)
        return {
            "dag_name": DAG_NAME,
            "should_check": window is not None,
            "window": None if window is None else window.__dict__,
            "checked_at": datetime.now(UTC).isoformat(),
        }

    def detect_available_pdfs(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Executa a deteccao de PDFs apenas quando o contexto indica janela ativa."""
        if not context.get("should_check") or not context.get("window"):
            return []

        window = DisclosureWindow(**context["window"])
        return self.ri_client.detect_operational_previews(window=window)

















SOURCE_DOCUMENT_PROCESSING_USE_CASE = SourceDocumentProcessingUseCase()

# Compatibilidade transitória para consumidores ainda não migrados.
DetectaPdfExtraiService = SourceDocumentProcessingUseCase
DETECTA_PDF_EXTRAI_SERVICE = SOURCE_DOCUMENT_PROCESSING_USE_CASE
