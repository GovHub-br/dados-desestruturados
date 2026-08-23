"""Servico de inventario do fallback composto por responsabilidades menores."""

from .inventory_evidence import FallbackInventoryEvidenceMixin
from .inventory_loading import FallbackInventoryLoadingMixin
from .inventory_policy import FallbackInventoryPolicyMixin


class FallbackInventoryService(
    FallbackInventoryLoadingMixin,
    FallbackInventoryPolicyMixin,
    FallbackInventoryEvidenceMixin,
):
    """Carrega inventario, amostras e evidencias de artefatos selecionados."""

    REQUIRED = "obrigatorio"
    RECOMMENDED = "recomendado"
    OPTIONAL = "opcional"
    DISABLED = "nao_usar_automaticamente"

    PARTIAL_SCOPE = "correcao_parcial_mapeamento"
    FULL_REMAP_SCOPE = "regeneracao_total_mapeamento"
    CREATION_SCOPE = "criacao_inicial_layout"
    UNSUPPORTED_SCOPE = "falha_nao_suportada_para_fallback_automatico"

    MAX_FULL_ARTIFACT_CHARS = 60_000
    MAX_FULL_TABLE_ROWS = 80
    MAX_FULL_TABLE_CHARS = 40_000
    TABLE_WINDOW_ROWS = 12
    JSONL_CHUNK_RECORDS = 40
    MAX_CHUNKS_PER_ARTIFACT = 8
    MAX_ANCHOR_EVIDENCES_PER_ARTIFACT = 12
    LLM_SELECTION_KINDS = frozenset({"table", "chart"})


FALLBACK_INVENTORY_SERVICE = FallbackInventoryService()

__all__ = ["FALLBACK_INVENTORY_SERVICE", "FallbackInventoryService"]
