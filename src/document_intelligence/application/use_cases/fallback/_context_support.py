"""Dependências de projeção dos payloads do fallback LLM."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from document_intelligence.domain.contracts.mapping_requirements import (
    mappable_targets_payload,
    mapping_requirements_from_context,
    mapping_requirements_payload,
)
from document_intelligence.domain.contracts.schema import (
    contract_literal_paths,
    schema_array_paths,
    schema_paths,
)
from document_intelligence.domain.fallback.classification import (
    FALLBACK_CLASSIFICATION_SERVICE,
    FallbackClassificationService,
)

from .inventory import FALLBACK_INVENTORY_SERVICE, FallbackInventoryService
