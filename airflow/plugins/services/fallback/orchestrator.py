"""Compatibilidade temporária; use ``document_processing.application``."""

from document_processing.application.use_cases.fallback.service import (
    FALLBACK_LLM_SERVICE,
    FallbackLlmService,
)

__all__ = ["FALLBACK_LLM_SERVICE", "FallbackLlmService"]
