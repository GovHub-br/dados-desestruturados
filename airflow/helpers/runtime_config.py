from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LocalPlatformConfig:
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool
    minio_bucket: str
    minio_document_prefix: str
    minio_extract_prefix: str
    minio_resolution_prefix: str
    minio_contract_prefix: str
    minio_layout_prefix: str
    pipeline_tmp_dir: str
    docling_runner_base_url: str
    docling_runner_timeout_seconds: int
    docling_runner_execution_timeout_seconds: int
    ri_download_timeout_seconds: int
    ri_download_max_attempts: int
    ri_download_retry_delay_seconds: int
    force_extract: bool
    dominio: str
    entidade: str
    tipo_documento: str
    docling_do_ocr: bool
    docling_do_chart_extraction: bool
    docling_enable_llm_text_extraction: bool


class RuntimeConfigLoader:
    """Carrega configuracoes de runtime a partir de variaveis de ambiente."""

    @staticmethod
    def _as_bool(value: str) -> bool:
        """Converte valores de ambiente em booleanos de forma tolerante."""
        return value.strip().lower() in {"1", "true", "yes", "sim"}

    @staticmethod
    def _as_int(value: str, *, default: int) -> int:
        """Converte valores de ambiente em inteiros com fallback previsivel."""
        try:
            return int(value.strip())
        except (AttributeError, TypeError, ValueError):
            return default

    def load_local_platform_config(self) -> LocalPlatformConfig:
        """Monta a configuracao usada pelos clientes e services do Airflow."""
        return LocalPlatformConfig(
            minio_endpoint=os.getenv("MINIO_ENDPOINT", "minio:9000"),
            minio_access_key=os.getenv("MINIO_ROOT_USER", "minioadmin"),
            minio_secret_key=os.getenv("MINIO_ROOT_PASSWORD", "minioadmin123"),
            minio_secure=self._as_bool(os.getenv("MINIO_SECURE", "false")),
            minio_bucket=os.getenv("MINIO_BUCKET_DATA_LAKE", "ocr-cidades"),
            minio_document_prefix=os.getenv(
                "MINIO_DOCUMENT_PREFIX",
                "documentos-origem/construtoras",
            ),
            minio_extract_prefix=os.getenv(
                "MINIO_EXTRACT_PREFIX",
                "execucoes/construtoras/extracao",
            ),
            minio_resolution_prefix=os.getenv(
                "MINIO_RESOLUTION_PREFIX",
                "execucoes/construtoras/resolucao",
            ),
            minio_contract_prefix=os.getenv(
                "MINIO_CONTRACT_PREFIX",
                "contratos/construtoras",
            ),
            minio_layout_prefix=os.getenv(
                "MINIO_LAYOUT_PREFIX",
                "layouts/construtoras",
            ),
            pipeline_tmp_dir=os.getenv("PIPELINE_TMP_DIR", "/opt/pipeline-tmp"),
            docling_runner_base_url=os.getenv("DOCLING_RUNNER_BASE_URL", "http://docling-runner:8081"),
            docling_runner_timeout_seconds=self._as_int(
                os.getenv("DOCLING_RUNNER_TIMEOUT_SECONDS", "4000"),
                default=4000,
            ),
            docling_runner_execution_timeout_seconds=self._as_int(
                os.getenv("DOCLING_RUNNER_EXECUTION_TIMEOUT_SECONDS", "3600"),
                default=3600,
            ),
            ri_download_timeout_seconds=self._as_int(
                os.getenv("RI_DOWNLOAD_TIMEOUT_SECONDS", "120"),
                default=120,
            ),
            ri_download_max_attempts=self._as_int(
                os.getenv("RI_DOWNLOAD_MAX_ATTEMPTS", "3"),
                default=3,
            ),
            ri_download_retry_delay_seconds=self._as_int(
                os.getenv("RI_DOWNLOAD_RETRY_DELAY_SECONDS", "5"),
                default=5,
            ),
            force_extract=self._as_bool(os.getenv("FORCE_EXTRACT", "false")),
            dominio=os.getenv("PIPELINE_DOMINIO", "construtoras"),
            entidade=os.getenv("PIPELINE_ENTIDADE", "cury"),
            tipo_documento=os.getenv(
                "PIPELINE_TIPO_DOCUMENTO",
                "relatorio_trimestral_construtora",
            ),
            docling_do_ocr=self._as_bool(
                os.getenv("DOCLING_DO_OCR", "true")
            ),
            docling_do_chart_extraction=self._as_bool(
                os.getenv("DOCLING_DO_CHART_EXTRACTION", "false")
            ),
            docling_enable_llm_text_extraction=self._resolve_llm_text_extraction_flag(),
        )

    def _resolve_llm_text_extraction_flag(self) -> bool:
        """Ativa LLM apenas quando a feature foi habilitada e a configuracao minima existe."""
        requested = self._as_bool(os.getenv("DOCLING_ENABLE_LLM_TEXT_EXTRACTION", "false"))
        if not requested:
            return False

        api_url = os.getenv("DOCLING_LLM_API_URL", "").strip() or os.getenv("LLM_API_URL", "").strip()
        api_model = os.getenv("DOCLING_LLM_API_MODEL", "").strip() or os.getenv("LLM_API_MODEL", "").strip()
        return bool(api_url and api_model)


RUNTIME_CONFIG_LOADER = RuntimeConfigLoader()
