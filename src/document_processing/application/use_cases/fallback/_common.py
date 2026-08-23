"""Dependências compartilhadas pelos componentes do fallback LLM.

Este módulo não contém fluxo operacional; apenas centraliza tipos e serviços
necessários aos casos de uso especializados.
"""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from document_processing.domain.fallback.artifact_selection_validation import (
    FALLBACK_ARTIFACT_SELECTION_VALIDATION_SERVICE,
    ArtifactSelectionValidationError,
    ArtifactSelectionValidationService,
)
from document_processing.domain.fallback.candidate_validation import (
    FALLBACK_CANDIDATE_VALIDATION_SERVICE,
    FallbackCandidateValidationService,
    UnmappedRequiredFieldsError,
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
    LayoutArtifactSelection,
    LayoutSignatureCandidate,
    LayoutSignatureFragment,
)
from document_processing.infrastructure.llm.client import (
    FALLBACK_LLM_CLIENT,
    FallbackLlmClient,
    FallbackLlmClientError,
)
from document_processing.infrastructure.storage.minio_artifact_repository import MinioStorageClient
from document_processing.infrastructure.storage.semantic_contract_registry import (
    SemanticContractRegistry,
)
from document_processing.shared.config.runtime import RUNTIME_CONFIG_LOADER, RuntimeConfigLoader

from .context_builder import FallbackProblemContextBuilder
from .inventory import FALLBACK_INVENTORY_SERVICE, FallbackInventoryService
from .prompts import (
    artifact_selection_repair_system_prompt,
    artifact_selection_system_prompt,
    candidate_artifacts_instruction,
    candidate_contract_instruction,
    candidate_final_instruction,
    candidate_layout_repair_system_prompt,
    candidate_scope_instruction,
    candidate_structure_instruction,
    unit_mapping_artifacts_instruction,
    unit_mapping_final_instruction,
    unit_mapping_repair_instruction,
    unit_mapping_scope_instruction,
    unit_mapping_structure_example,
    unit_mapping_structure_instruction,
)
