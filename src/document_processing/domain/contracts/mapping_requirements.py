from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from document_processing.domain.layouts.paths import parse_mapping_path


class MappingRequirementsError(RuntimeError):
    """O contrato declarou requisitos de mapeamento inconsistentes."""


# Tipos de origem que um layout signature pode declarar. Espelha
# ``SupportedMappingOrigin`` (domain/fallback/models.py); um teste garante a igualdade.
TIPOS_DE_EVIDENCIA = frozenset(
    {
        "valor_fixo",
        "campo_derivado",
        "campo_json",
        "bloco_textual",
        "registros_de_blocos_textuais",
        "cabecalho_de_tabela",
        "celula_de_tabela",
        "linhas_de_tabela",
        "juncao_de_registros_json",
    }
)


@dataclass(frozen=True)
class RequiredObservation:
    """Uma observacao declarada de um campo repetivel do schema de saida."""

    selectors: dict[str, str]
    context_fields: tuple[str, ...]
    required: bool = True


@dataclass(frozen=True)
class MappingRequirement:
    """Um campo do schema que precisa de origem deterministica no layout."""

    path: str
    observations: tuple[RequiredObservation, ...]
    descricao: str | None = None
    orientacao_origem: dict[str, Any] | None = None
    # campo terminal ou de contexto -> tipo_origem que o contrato espera para ele.
    evidencia_esperada: dict[str, str] | None = None


@dataclass(frozen=True)
class RoleSpec:
    """Um papel que um seletor de observacao pode assumir (``papeis.<seletor>.<papel>``).

    ``derivacao`` e opcional e generica: diz como o rotulo do papel se calcula a
    partir da identidade do documento (``{"origem": "identidade_documento.periodo"}``)
    ou de outro papel (``{"relacao": "anterior", "passo": 1}``). O contrato decide
    se declara; o codigo nunca assume um papel que nao esteja aqui.
    """

    seletor: str
    papel: str
    descricao: str
    derivacao: dict[str, Any] | None = None


def role_specs_from_context(contract_context: Any) -> list[RoleSpec]:
    """Le ``requisitos_mapeamento.papeis`` e confere que cada seletor e usado."""
    requirements = _requirements_block(contract_context)
    raw_roles = requirements.get("papeis")
    if raw_roles in (None, {}):
        return []
    if not isinstance(raw_roles, dict):
        raise MappingRequirementsError("requisitos_mapeamento.papeis deve ser um objeto.")
    used_selectors = _selector_values_by_key(requirements)
    specs: list[RoleSpec] = []
    for selector, roles in raw_roles.items():
        clean_selector = str(selector).strip()
        if not clean_selector or not isinstance(roles, dict) or not roles:
            raise MappingRequirementsError(
                f"papeis.{selector} deve ser um objeto papel -> definicao nao vazio."
            )
        if clean_selector not in used_selectors:
            raise MappingRequirementsError(
                f"papeis.{clean_selector} nao e seletor de nenhuma observacao obrigatoria."
            )
        for role, definition in roles.items():
            clean_role = str(role).strip()
            if not clean_role or not isinstance(definition, dict):
                raise MappingRequirementsError(
                    f"papeis.{clean_selector}.{role} deve ser um objeto com descricao."
                )
            descricao = str(definition.get("descricao", "")).strip()
            if not descricao:
                raise MappingRequirementsError(
                    f"papeis.{clean_selector}.{clean_role} sem descricao."
                )
            derivacao = definition.get("derivacao")
            if derivacao is not None and not isinstance(derivacao, dict):
                raise MappingRequirementsError(
                    f"papeis.{clean_selector}.{clean_role}.derivacao deve ser objeto."
                )
            specs.append(RoleSpec(clean_selector, clean_role, descricao, derivacao))
        declared = {spec.papel for spec in specs if spec.seletor == clean_selector}
        undeclared = sorted(used_selectors[clean_selector] - declared)
        if undeclared:
            raise MappingRequirementsError(
                f"observacoes usam papeis de {clean_selector} nao declarados: {undeclared}."
            )
    return specs


def roles_payload(specs: list[RoleSpec]) -> dict[str, dict[str, Any]]:
    """``papeis`` no formato do contrato, para projetar no payload da LLM."""
    payload: dict[str, dict[str, Any]] = {}
    for spec in specs:
        entry: dict[str, Any] = {"descricao": spec.descricao}
        if spec.derivacao:
            entry["derivacao"] = spec.derivacao
        payload.setdefault(spec.seletor, {})[spec.papel] = entry
    return payload


def _requirements_block(contract_context: Any) -> dict[str, Any]:
    if not isinstance(contract_context, dict):
        return {}
    semantic = contract_context.get("contrato_semantico", {})
    requirements = semantic.get("requisitos_mapeamento", {}) if isinstance(semantic, dict) else {}
    return requirements if isinstance(requirements, dict) else {}


def _selector_values_by_key(requirements: dict[str, Any]) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    for field in requirements.get("campos_obrigatorios", []) or []:
        if not isinstance(field, dict):
            continue
        for observation in field.get("observacoes_obrigatorias", []) or []:
            selectors = observation.get("seletores", {}) if isinstance(observation, dict) else {}
            for key, value in dict(selectors).items():
                values.setdefault(str(key).strip(), set()).add(str(value).strip())
    return values


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
        descricao = str(raw_requirement.get("descricao", "")).strip() or None
        orientacao_origem = raw_requirement.get("orientacao_origem")
        if orientacao_origem is not None and not isinstance(orientacao_origem, dict):
            raise MappingRequirementsError(
                f"orientacao_origem deve ser objeto: {path}."
            )
        evidencia_esperada = _parse_expected_evidence(
            raw_requirement.get("evidencia_esperada"),
            path=path,
            observations=observations,
        )
        parsed.append(
            MappingRequirement(
                path=path,
                observations=observations,
                descricao=descricao,
                orientacao_origem=orientacao_origem,
                evidencia_esperada=evidencia_esperada,
            )
        )

    return parsed


def _parse_expected_evidence(
    raw: Any,
    *,
    path: str,
    observations: tuple[RequiredObservation, ...],
) -> dict[str, str] | None:
    """``evidencia_esperada``: campo (terminal ou de contexto) -> tipo_origem."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or not raw:
        raise MappingRequirementsError(
            f"evidencia_esperada deve ser objeto campo -> tipo_origem: {path}."
        )
    leaf = path.rpartition(".")[2]
    known_fields = {leaf, *(field for obs in observations for field in obs.context_fields)}
    parsed: dict[str, str] = {}
    for field, origin in raw.items():
        clean_field = str(field).strip()
        clean_origin = str(origin).strip()
        if clean_field not in known_fields:
            raise MappingRequirementsError(
                f"evidencia_esperada de {path} cita campo desconhecido {clean_field!r}; "
                f"aceitos: {sorted(known_fields)}."
            )
        if clean_origin not in TIPOS_DE_EVIDENCIA:
            raise MappingRequirementsError(
                f"evidencia_esperada de {path} usa tipo_origem desconhecido {clean_origin!r}."
            )
        parsed[clean_field] = clean_origin
    return parsed


def mapping_requirements_payload(
    requirements: list[MappingRequirement],
) -> dict[str, Any]:
    """Converte requisitos validados para o payload legivel pela LLM."""
    return {
        "campos_obrigatorios": [
            {
                "path": requirement.path,
                **({"descricao": requirement.descricao} if requirement.descricao else {}),
                **(
                    {"orientacao_origem": requirement.orientacao_origem}
                    if requirement.orientacao_origem
                    else {}
                ),
                **(
                    {"evidencia_esperada": requirement.evidencia_esperada}
                    if requirement.evidencia_esperada
                    else {}
                ),
                **(
                    {
                        "observacoes_obrigatorias": [
                            {
                                "seletores": observation.selectors,
                                "campos_contexto_obrigatorios": list(
                                    observation.context_fields
                                ),
                                **(
                                    {"obrigatorio": False}
                                    if not observation.required
                                    else {}
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
                {"evidencia_esperada": requirement.evidencia_esperada}
                if requirement.evidencia_esperada
                else {}
            ),
            **(
                {
                    "observacoes_obrigatorias": [
                        {
                            "seletores": observation.selectors,
                            "campos_contexto_obrigatorios": list(
                                observation.context_fields
                            ),
                            **(
                                {"obrigatorio": False}
                                if not observation.required
                                else {}
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
    for token in parse_mapping_path(path):
        normalized_parts.append(str(token["field"]))
        selector = token.get("selector")
        if selector:
            selector_key, selector_value = selector
            selectors[str(selector_key)] = str(selector_value)
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
    required = raw_observation.get("obrigatorio", True)
    if not isinstance(required, bool):
        raise MappingRequirementsError(
            f"obrigatorio deve ser booleano: {path}."
        )
    return RequiredObservation(
        selectors=selectors,
        context_fields=context_fields,
        required=required,
    )
