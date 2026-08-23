"""Compatibilidade temporária para imports legados do fallback LLM."""

from document_processing.application.use_cases.fallback import (
    FALLBACK_INVENTORY_SERVICE,
    FALLBACK_LLM_SERVICE,
    FALLBACK_PROBLEM_CONTEXT_BUILDER,
    FallbackInventoryService,
    FallbackLlmService,
    FallbackProblemContextBuilder,
)
from document_processing.domain.fallback.artifact_selection_validation import (
    FALLBACK_ARTIFACT_SELECTION_VALIDATION_SERVICE,
    ArtifactSelectionValidationError,
    ArtifactSelectionValidationService,
)
from document_processing.domain.fallback.candidate_validation import (
    FALLBACK_CANDIDATE_VALIDATION_SERVICE,
    FallbackCandidateValidationService,
)
from document_processing.domain.fallback.classification import (
    FALLBACK_CLASSIFICATION_SERVICE,
    FallbackClassificationService,
)
from document_processing.domain.fallback.mapping_plan import (
    MAPPING_PLAN_SERVICE,
    MappingPlanService,
    MappingUnit,
)
from document_processing.domain.fallback.models import (
    ArtifactSelectionCoverage,
    ArtifactSelectionItem,
    BaseLayoutSignatureRef,
    LayoutArtifactSelection,
    LayoutSignatureCandidate,
    LayoutSignatureFragment,
)

__all__ = [name for name in globals() if name.startswith("FALLBACK_") or name.endswith(("Service", "Unit", "Candidate", "Fragment", "Selection", "Item", "Coverage", "Ref", "Error"))]
