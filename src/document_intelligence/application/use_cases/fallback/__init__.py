"""Casos de uso do fallback LLM da plataforma documental."""

from .context_builder import FALLBACK_PROBLEM_CONTEXT_BUILDER, FallbackProblemContextBuilder
from .inventory import FALLBACK_INVENTORY_SERVICE, FallbackInventoryService
from .service import FALLBACK_LLM_SERVICE, FallbackLlmService

__all__ = [
    "FALLBACK_INVENTORY_SERVICE",
    "FALLBACK_LLM_SERVICE",
    "FALLBACK_PROBLEM_CONTEXT_BUILDER",
    "FallbackInventoryService",
    "FallbackLlmService",
    "FallbackProblemContextBuilder",
]
