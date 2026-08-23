"""Fachada de compatibilidade do fallback LLM da DAG 3.

O fluxo é implementado por componentes coesos. Esta classe preserva a API usada
pela DAG durante a transição e é o ponto único de composição das dependências.
"""

from __future__ import annotations

from typing import Any

from ._common import *  # noqa: F401,F403
from .artifact_selection import ArtifactSelectionMixin
from .candidate_composition import CandidateCompositionMixin
from .candidate_generation import CandidateGenerationMixin
from .candidate_json_generation import CandidateJsonGenerationMixin
from .candidate_lifecycle import CandidateLifecycleMixin
from .context_loading import FallbackContextLoadingMixin
from .fragment_generation import FragmentGenerationMixin
from .mapping_unit_generation import MappingUnitGenerationMixin
from .storage_access import FallbackStorageAccessMixin
from .trace_persistence import FallbackTracePersistenceMixin


class FallbackLlmService(
    FallbackContextLoadingMixin,
    CandidateGenerationMixin,
    MappingUnitGenerationMixin,
    FragmentGenerationMixin,
    CandidateJsonGenerationMixin,
    CandidateLifecycleMixin,
    ArtifactSelectionMixin,
    FallbackTracePersistenceMixin,
    CandidateCompositionMixin,
    FallbackStorageAccessMixin,
):
    """Coordena o fallback assistido por LLM sem concentrar suas etapas."""

    PARTIAL_SCOPE = "correcao_parcial_mapeamento"
    FULL_REMAP_SCOPE = "regeneracao_total_mapeamento"
    CREATION_SCOPE = "criacao_inicial_layout"
    UNSUPPORTED_SCOPE = "falha_nao_suportada_para_fallback_automatico"
    MAX_CANDIDATE_CORRECTION_ATTEMPTS = 3
    MAX_ARTIFACT_SELECTION_CORRECTION_ATTEMPTS = 3

    def _llm_options_for_stage(self, stage: str) -> dict[str, Any]:
        """Centraliza o orçamento por responsabilidade, sem regra de domínio."""
        config = self.config_loader.load_local_platform_config()
        if stage == "selecao_artefatos":
            return {
                "max_tokens": getattr(config, "fallback_llm_selection_max_tokens", 2048),
                "thinking_mode": getattr(
                    config, "fallback_llm_selection_thinking_mode", "disabled"
                ),
            }
        if stage in {"fragmento_layout_signature", "layout_signature_candidato"}:
            return {
                "max_tokens": getattr(config, "fallback_llm_fragment_max_tokens", 8192),
                "thinking_mode": getattr(
                    config, "fallback_llm_fragment_thinking_mode", "enabled"
                ),
            }
        return {
            "max_tokens": config.fallback_llm_max_tokens,
            "thinking_mode": config.fallback_llm_thinking_mode,
        }

    def __init__(
        self,
        *,
        config_loader: RuntimeConfigLoader | None = None,
        minio_client: MinioStorageClient | None = None,
        llm_client: FallbackLlmClient | None = None,
        candidate_validator: FallbackCandidateValidationService | None = None,
        artifact_selection_validator: ArtifactSelectionValidationService | None = None,
        inventory_service: FallbackInventoryService | None = None,
        classification_service: FallbackClassificationService | None = None,
        context_builder: FallbackProblemContextBuilder | None = None,
        mapping_plan_service: MappingPlanService | None = None,
    ) -> None:
        self.config_loader = config_loader or RUNTIME_CONFIG_LOADER
        self._minio_client = minio_client
        self.llm_client = llm_client or FALLBACK_LLM_CLIENT
        self.candidate_validator = candidate_validator or FALLBACK_CANDIDATE_VALIDATION_SERVICE
        self.artifact_selection_validator = (
            artifact_selection_validator or FALLBACK_ARTIFACT_SELECTION_VALIDATION_SERVICE
        )
        self.inventory_service = inventory_service or FALLBACK_INVENTORY_SERVICE
        self.classification_service = classification_service or FALLBACK_CLASSIFICATION_SERVICE
        self.context_builder = context_builder or FallbackProblemContextBuilder(
            classification_service=self.classification_service,
            inventory_service=self.inventory_service,
        )
        self.mapping_plan_service = mapping_plan_service or MAPPING_PLAN_SERVICE

    @property
    def minio_client(self) -> MinioStorageClient:
        """Cria o repositório MinIO somente quando uma etapa precisa de artefatos."""
        if self._minio_client is None:
            config = self.config_loader.load_local_platform_config()
            self._minio_client = MinioStorageClient(config)
        return self._minio_client


FALLBACK_LLM_SERVICE = FallbackLlmService()
