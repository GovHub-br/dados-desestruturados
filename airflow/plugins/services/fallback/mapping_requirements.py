from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class MappingRequirementsError(RuntimeError):
    """O contrato declarou requisitos de mapeamento inconsistentes."""


@dataclass(frozen=True)
class RequiredObservation:
    """Uma observacao obrigatoria de um campo repetivel do schema de saida."""

    selectors: dict[str, str]
    context_fields: tuple[str, ...]


@dataclass(frozen=True)
class MappingRequirement:
    """Um campo do schema que precisa de origem deterministica no layout."""

    path: str
    observations: tuple[RequiredObservation, ...]


def mapping_requirements_from_context(
    contract_context: Any,
    *,
    validate_schema_paths: bool = True,
) -> list[MappingRequirement]:
    """Le requisitos declarados no contrato relevante e valida seus paths."""
    if not isinstance(contract_context, dict):
        raise MappingRequirementsError("Contexto do contrato semantico invalido.")

    semantic = contract_context.get("contrato_semantico", {})
    requirements = (
        semantic.get("requisitos_mapeamento", {})
        if isinstance(semantic, dict)
        else {}
    )
    raw_fields = (
        requirements.get("campos_obrigatorios", [])
        if isinstance(requirements, dict)
        else []
    )
    if not isinstance(raw_fields, list) or not raw_fields:
        raise MappingRequirementsError(
            "Contrato semantico sem "
            "contrato_semantico.requisitos_mapeamento.campos_obrigatorios."
        )

    structure = contract_context.get("estrutura_schema_saida", {})
    raw_paths = (
        structure.get("paths_permitidos", [])
        if isinstance(structure, dict)
        else []
    )
    allowed_paths = {str(path).strip() for path in raw_paths if str(path).strip()}
    parsed: list[MappingRequirement] = []
    seen_paths: set[str] = set()

    for raw_requirement in raw_fields:
        if not isinstance(raw_requirement, dict):
            raise MappingRequirementsError(
                "Cada campos_obrigatorios deve ser um objeto com path."
            )
        path = str(raw_requirement.get("path", "")).strip()
        if not path:
            raise MappingRequirementsError("Campo obrigatorio de mapeamento sem path.")
        if path in seen_paths:
            raise MappingRequirementsError(
                f"Campo obrigatorio de mapeamento duplicado: {path}."
            )
        if validate_schema_paths and path not in allowed_paths:
            raise MappingRequirementsError(
                "Contrato semantico declarou campo obrigatorio fora do schema_saida: "
                f"{path}."
            )
        seen_paths.add(path)

        raw_observations = raw_requirement.get("observacoes_obrigatorias", [])
        if not isinstance(raw_observations, list):
            raise MappingRequirementsError(
                f"observacoes_obrigatorias deve ser lista: {path}."
            )
        observations = tuple(
            _parse_observation(
                raw_observation,
                path=path,
                allowed_paths=allowed_paths,
                validate_schema_paths=validate_schema_paths,
            )
            for raw_observation in raw_observations
        )
        parsed.append(MappingRequirement(path=path, observations=observations))

    return parsed


def mapping_requirements_payload(
    requirements: list[MappingRequirement],
) -> dict[str, list[dict[str, Any]]]:
    """Converte requisitos validados para o payload legivel pela LLM."""
    return {
        "campos_obrigatorios": [
            {
                "path": requirement.path,
                **(
                    {
                        "observacoes_obrigatorias": [
                            {
                                "seletores": observation.selectors,
                                "campos_contexto_obrigatorios": list(
                                    observation.context_fields
                                ),
                            }
                            for observation in requirement.observations
                        ]
                    }
                    if requirement.observations
                    else {}
                ),
            }
            for requirement in requirements
        ]
    }


def mappable_targets_payload(
    requirements: list[MappingRequirement],
    *,
    array_paths: list[Any],
) -> list[dict[str, Any]]:
    """Converte requisitos em alvos concretos para a geracao do candidato."""
    normalized_arrays = [str(path).strip() for path in array_paths if str(path).strip()]
    return [
        {
            "campo_saida": requirement.path,
            "arrays_que_exigem_seletor": [
                array_path
                for array_path in normalized_arrays
                if requirement.path == array_path
                or requirement.path.startswith(f"{array_path}.")
            ],
            **(
                {
                    "observacoes_obrigatorias": [
                        {
                            "seletores": observation.selectors,
                            "campos_contexto_obrigatorios": list(
                                observation.context_fields
                            ),
                        }
                        for observation in requirement.observations
                    ]
                }
                if requirement.observations
                else {}
            ),
        }
        for requirement in requirements
    ]


def parsed_mapping_path(path: str) -> tuple[str, dict[str, str]]:
    """Remove filtros de array de um path e devolve os seletores declarados."""
    selectors: dict[str, str] = {}
    normalized_parts: list[str] = []
    for raw_part in path.split("."):
        part = raw_part.strip()
        base = part.split("[", maxsplit=1)[0].strip()
        if base:
            normalized_parts.append(base)
        for selector_key, selector_value in re.findall(r"\[([^=\]]+)=([^\]]+)\]", part):
            selectors[selector_key.strip()] = selector_value.strip()
    return ".".join(normalized_parts), selectors


def _parse_observation(
    raw_observation: Any,
    *,
    path: str,
    allowed_paths: set[str],
    validate_schema_paths: bool,
) -> RequiredObservation:
    if not isinstance(raw_observation, dict):
        raise MappingRequirementsError(
            f"Observacao obrigatoria invalida para {path}."
        )
    raw_selectors = raw_observation.get("seletores", {})
    if not isinstance(raw_selectors, dict) or not raw_selectors:
        raise MappingRequirementsError(
            f"Observacao obrigatoria sem seletores: {path}."
        )
    selectors = {
        str(key).strip(): str(value).strip()
        for key, value in raw_selectors.items()
        if str(key).strip() and str(value).strip()
    }
    if not selectors:
        raise MappingRequirementsError(
            f"Observacao obrigatoria sem seletores validos: {path}."
        )

    raw_context_fields = raw_observation.get("campos_contexto_obrigatorios", [])
    if not isinstance(raw_context_fields, list):
        raise MappingRequirementsError(
            f"campos_contexto_obrigatorios deve ser lista: {path}."
        )
    context_fields = tuple(
        str(field).strip() for field in raw_context_fields if str(field).strip()
    )
    parent_path, separator, _leaf = path.rpartition(".")
    if not separator:
        raise MappingRequirementsError(
            f"Campo obrigatorio sem campo terminal: {path}."
        )
    invalid_context_paths = [
        f"{parent_path}.{field}"
        for field in context_fields
        if f"{parent_path}.{field}" not in allowed_paths
    ]
    if validate_schema_paths and invalid_context_paths:
        raise MappingRequirementsError(
            "Campos de contexto fora do schema_saida: "
            f"{invalid_context_paths}."
        )
    return RequiredObservation(selectors=selectors, context_fields=context_fields)
