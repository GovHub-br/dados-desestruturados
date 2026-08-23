"""Compatibilidade temporária; use ``document_intelligence.application``."""

from document_intelligence.application.use_cases.fallback.service import (
    FALLBACK_LLM_SERVICE,
    FallbackLlmService,
)

__all__ = ["FALLBACK_LLM_SERVICE", "FallbackLlmService"]
