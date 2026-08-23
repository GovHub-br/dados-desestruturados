"""Prompts do fallback organizados por etapa, com API publica estavel."""

from .candidate_prompts import (
    artifact_selection_repair_system_prompt,
    artifact_selection_system_prompt,
    candidate_artifacts_instruction,
    candidate_contract_instruction,
    candidate_final_instruction,
    candidate_layout_repair_system_prompt,
    candidate_scope_instruction,
    candidate_structure_instruction,
)
from .unit_mapping_prompts import (
    unit_mapping_artifacts_instruction,
    unit_mapping_final_instruction,
    unit_mapping_repair_instruction,
    unit_mapping_scope_instruction,
    unit_mapping_structure_example,
    unit_mapping_structure_instruction,
)

__all__ = [
    "artifact_selection_repair_system_prompt",
    "artifact_selection_system_prompt",
    "candidate_artifacts_instruction",
    "candidate_contract_instruction",
    "candidate_final_instruction",
    "candidate_layout_repair_system_prompt",
    "candidate_scope_instruction",
    "candidate_structure_instruction",
    "unit_mapping_artifacts_instruction",
    "unit_mapping_final_instruction",
    "unit_mapping_repair_instruction",
    "unit_mapping_scope_instruction",
    "unit_mapping_structure_example",
    "unit_mapping_structure_instruction",
]
