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
    fallback_llm_provider: str
    fallback_llm_api_url: str
    fallback_llm_api_key: str
    fallback_llm_model: str
    fallback_llm_timeout_seconds: int
    fallback_llm_max_tokens: int
    fallback_llm_thinking_mode: str
    fallback_llm_selection_max_tokens: int
    fallback_llm_selection_thinking_mode: str
    fallback_llm_fragment_max_tokens: int
    fallback_llm_fragment_thinking_mode: str
    langfuse_enabled: bool
    langfuse_base_url: str
    langfuse_public_key: str
    langfuse_secret_key: str
    langfuse_environment: str
    langfuse_release: str
    langfuse_timeout_seconds: int
    langfuse_sample_rate: float
    prompts_langfuse_enabled: bool
    prompt_label: str


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
            fallback_llm_provider=os.getenv("FALLBACK_LLM_PROVIDER", "openai").strip().lower(),
            fallback_llm_api_url=os.getenv("FALLBACK_LLM_API_URL", "").strip(),
            fallback_llm_api_key=(
                os.getenv("FALLBACK_LLM_API_KEY", "").strip()
                or os.getenv("OPENAI_API_KEY", "").strip()
            ),
            fallback_llm_model=os.getenv("FALLBACK_LLM_MODEL", "").strip(),
            fallback_llm_timeout_seconds=self._as_int(
                os.getenv("FALLBACK_LLM_TIMEOUT_SECONDS", "180"),
                default=180,
            ),
            fallback_llm_max_tokens=self._as_int(
                os.getenv("FALLBACK_LLM_MAX_TOKENS", "4096"),
                default=4096,
            ),
            fallback_llm_thinking_mode=os.getenv(
                "FALLBACK_LLM_THINKING_MODE", ""
            ).strip().lower(),
            fallback_llm_selection_max_tokens=self._as_int(
                os.getenv("FALLBACK_LLM_SELECTION_MAX_TOKENS", "2048"),
                default=2048,
            ),
            fallback_llm_selection_thinking_mode=os.getenv(
                "FALLBACK_LLM_SELECTION_THINKING_MODE", "disabled"
            ).strip().lower(),
            fallback_llm_fragment_max_tokens=self._as_int(
                os.getenv("FALLBACK_LLM_FRAGMENT_MAX_TOKENS", "8192"),
                default=8192,
            ),
            fallback_llm_fragment_thinking_mode=os.getenv(
                "FALLBACK_LLM_FRAGMENT_THINKING_MODE", "enabled"
            ).strip().lower(),
            langfuse_enabled=self._resolve_langfuse_enabled_flag(),
            langfuse_base_url=os.getenv("LANGFUSE_BASE_URL", "").strip().rstrip("/"),
            langfuse_public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "").strip(),
            langfuse_secret_key=os.getenv("LANGFUSE_SECRET_KEY", "").strip(),
            langfuse_environment=os.getenv(
                "LANGFUSE_ENVIRONMENT", "development"
            ).strip().lower(),
            langfuse_release=self._resolve_langfuse_release(),
            langfuse_timeout_seconds=self._as_int(
                os.getenv("LANGFUSE_TIMEOUT_SECONDS", "10"), default=10
            ),
            langfuse_sample_rate=self._as_float(
                os.getenv("LANGFUSE_SAMPLE_RATE", "1.0"), default=1.0
            ),
            prompts_langfuse_enabled=self._resolve_prompts_langfuse_flag(),
            prompt_label=os.getenv("ATLAS_PROMPT_LABEL", "production").strip()
            or "production",
        )

    @staticmethod
    def _as_float(value: str, *, default: float) -> float:
        """Converte valores de ambiente em float com fallback previsivel."""
        try:
            return float(str(value).strip())
        except (AttributeError, TypeError, ValueError):
            return default

    def _resolve_langfuse_enabled_flag(self) -> bool:
        """Habilita observabilidade apenas quando a credencial minima existe."""
        requested = self._as_bool(os.getenv("LANGFUSE_ENABLED", "true"))
        if not requested:
            return False
        return bool(
            os.getenv("LANGFUSE_BASE_URL", "").strip()
            and os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
            and os.getenv("LANGFUSE_SECRET_KEY", "").strip()
        )

    def _resolve_prompts_langfuse_flag(self) -> bool:
        """Habilita a resolucao de prompts pelo Langfuse.

        Desligado por padrao: ligar muda a origem do texto enviado a LLM, e essa
        mudanca precisa ser medida contra a linha de base antes de virar o normal.
        Sem as credenciais nao ha o que resolver, entao a flag nao tem efeito.
        """
        if not self._as_bool(os.getenv("ATLAS_PROMPTS_LANGFUSE_ENABLED", "false")):
            return False
        return self._resolve_langfuse_enabled_flag()

    @staticmethod
    def _resolve_langfuse_release() -> str:
        """Rotulo de versao do projeto usado para comparar execucoes entre mudancas."""
        explicit = os.getenv("ATLAS_RELEASE", "").strip()
        if explicit:
            return explicit
        configured = os.getenv("LANGFUSE_RELEASE", "").strip()
        if configured:
            return configured
        from document_processing.shared.config.release import resolve_release

        return resolve_release(
            os.getenv("LANGFUSE_ENVIRONMENT", "development").strip().lower()
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
