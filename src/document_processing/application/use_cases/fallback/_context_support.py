"""Dependências de projeção dos payloads do fallback LLM."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from document_processing.domain.contracts.capabilities import (
    derived_paths,
    item_key_identity_attributes,
    item_key_origins,
    item_keys,
)
from document_processing.domain.contracts.mapping_requirements import (
    mappable_targets_payload,
    mapping_requirements_from_context,
    mapping_requirements_payload,
    role_specs_from_context,
)
from document_processing.domain.contracts.schema import (
    contract_literal_paths,
    schema_array_paths,
    schema_paths,
)
from document_processing.domain.fallback.classification import (
    FALLBACK_CLASSIFICATION_SERVICE,
    FallbackClassificationService,
)
from document_processing.domain.fallback.target_enumeration import (
    enumerate_target_entries,
    expected_entries_payload,
)

from .inventory import FALLBACK_INVENTORY_SERVICE, FallbackInventoryService
