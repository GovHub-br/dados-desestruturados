"""Pre-filtro deterministico da evidencia antes da selecao por LLM (fase 0).

Para cada requisito do contrato, deriva os termos de busca (nomes e sinonimos
do grupo de metricas, dos indicadores selecionados e das entidades de contexto)
e marca quais artefatos do inventario os contem. A LLM continua escolhendo, mas
entre candidatos; o validador recusa o que ficou fora.

Nenhum termo e conhecido pelo codigo: tudo sai do contrato. Um artefato cujo
resumo nao mostra todas as linhas (``row_count`` maior que a amostra de rotulos)
nao pode ser excluido pelo que nao foi visto e entra como candidato com o motivo
``amostra_incompleta``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from document_processing.domain.contracts.mapping_requirements import (
    MappingRequirement,
    MappingRequirementsError,
    mapping_requirements_from_context,
)
from document_processing.domain.contracts.text_normalization import normalize_text

MIN_TERM_LENGTH = 3


@dataclass(frozen=True)
class RequirementSearchCriteria:
    """Termos de busca de um requisito, ja normalizados, com a sua origem."""

    requisito: str
    termos: dict[str, str] = field(default_factory=dict)  # termo normalizado -> origem


@dataclass(frozen=True)
class ArtifactCandidate:
    path: str
    motivo: str  # "termo_casado" | "amostra_incompleta"
    termos_casados: tuple[str, ...] = ()


def search_criteria_by_requirement(contract_context: Any) -> dict[str, RequirementSearchCriteria]:
    """Deriva do contrato os termos que identificam a evidencia de cada requisito."""
    try:
        requirements = mapping_requirements_from_context(contract_context, validate_schema_paths=False)
    except MappingRequirementsError:
        return {}
    semantic = _semantic(contract_context)
    metrics = semantic.get("metricas", {}) if isinstance(semantic.get("metricas"), dict) else {}
    entities = semantic.get("entidades", {}) if isinstance(semantic.get("entidades"), dict) else {}
    criteria: dict[str, RequirementSearchCriteria] = {}
    for requirement in requirements:
        criteria[requirement.path] = RequirementSearchCriteria(
            requisito=requirement.path,
            termos=_terms_for_requirement(requirement, metrics=metrics, entities=entities),
        )
    return criteria


def prefilter_inventory(
    inventory_items: list[Any],
    contract_context: Any,
) -> dict[str, list[ArtifactCandidate]]:
    """requisito -> artefatos candidatos, na ordem do inventario."""
    criteria = search_criteria_by_requirement(contract_context)
    result: dict[str, list[ArtifactCandidate]] = {}
    for requisito, spec in criteria.items():
        candidates: list[ArtifactCandidate] = []
        for item in inventory_items:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).strip("/")
            if not path:
                continue
            text = _item_text(item)
            matched = tuple(sorted(term for term in spec.termos if term in text))
            if matched:
                candidates.append(ArtifactCandidate(path, "termo_casado", matched))
            elif _sample_is_incomplete(item):
                candidates.append(ArtifactCandidate(path, "amostra_incompleta"))
        result[requisito] = candidates
    return result


def prefilter_payload(prefiltered: dict[str, list[ArtifactCandidate]]) -> dict[str, Any]:
    """Forma serializavel: paths por requisito e a justificativa de cada um."""
    return {
        requisito: [
            {
                "path": candidate.path,
                "motivo": candidate.motivo,
                **({"termos_casados": list(candidate.termos_casados)} if candidate.termos_casados else {}),
            }
            for candidate in candidates
        ]
        for requisito, candidates in prefiltered.items()
    }


def candidate_paths_by_requirement(prefilter: Any) -> dict[str, set[str]]:
    """Le o payload serializado de volta como requisito -> conjunto de paths."""
    if not isinstance(prefilter, dict):
        return {}
    result: dict[str, set[str]] = {}
    for requisito, candidates in prefilter.items():
        paths: set[str] = set()
        if isinstance(candidates, list):
            for candidate in candidates:
                path = candidate.get("path") if isinstance(candidate, dict) else candidate
                if isinstance(path, str) and path.strip():
                    paths.add(path.strip("/"))
        result[str(requisito)] = paths
    return result


def _terms_for_requirement(
    requirement: MappingRequirement,
    *,
    metrics: dict[str, Any],
    entities: dict[str, Any],
) -> dict[str, str]:
    terms: dict[str, str] = {}

    def add(values: Any, origin: str) -> None:
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            return
        for value in values:
            normalized = normalize_text(value)
            if len(normalized) >= MIN_TERM_LENGTH:
                terms.setdefault(normalized, origin)

    # Grupo de metricas nomeado por um segmento do path do requisito.
    path_segments = requirement.path.split(".")
    selected_indicators = {
        str(value) for observation in requirement.observations for value in observation.selectors.values()
    }
    for metric_name, metric_spec in metrics.items():
        if not isinstance(metric_spec, dict):
            continue
        indicators = metric_spec.get("indicadores", {})
        indicators = indicators if isinstance(indicators, dict) else {}
        group_named_in_path = metric_name in path_segments
        group_has_selected_indicator = bool(selected_indicators & set(indicators))
        if not (group_named_in_path or group_has_selected_indicator):
            continue
        add(metric_name.replace("_", " "), f"metrica:{metric_name}")
        add(metric_spec.get("sinonimos"), f"metrica:{metric_name}")
        for indicator_name, indicator_spec in indicators.items():
            if not isinstance(indicator_spec, dict):
                continue
            # Com seletores de indicador, so os indicadores selecionados; sem
            # seletores de indicador (papeis, por exemplo), todos os do grupo.
            if selected_indicators & set(indicators) and indicator_name not in selected_indicators:
                continue
            add(indicator_name.replace("_", " "), f"indicador:{indicator_name}")
            add(indicator_spec.get("sinonimos"), f"indicador:{indicator_name}")

    # Entidades nomeadas nos seletores ou no contexto: o valor do seletor que for
    # elemento do dominio de uma entidade traz os sinonimos dessa entidade.
    for entity_name, entity_spec in entities.items():
        if not isinstance(entity_spec, dict):
            continue
        raw_domain = entity_spec.get("dominio")
        domain = {str(item) for item in raw_domain} if isinstance(raw_domain, list) else set()
        if selected_indicators & domain:
            add(entity_spec.get("sinonimos"), f"entidade:{entity_name}")

    guidance = requirement.orientacao_origem or {}
    for key in ("termos", "ancoras", "rotulos"):
        add(guidance.get(key), "orientacao_origem")
    return terms


def _item_text(item: dict[str, Any]) -> str:
    parts: list[Any] = [item.get("name"), item.get("section_title")]
    for key in ("schema", "row_labels_sample"):
        values = item.get(key)
        if isinstance(values, list):
            parts.extend(values)
    return " | ".join(normalize_text(part) for part in parts if part is not None)


def _sample_is_incomplete(item: dict[str, Any]) -> bool:
    """O resumo mostrou todas as linhas? Sem ``row_count`` e sem amostra, nao se sabe.

    Graficos chegam sem rotulos de linha e tabelas trazem uma amostra curta; um
    artefato que nao foi visto inteiro nao pode ser descartado por ausencia de termo.
    """
    sample = item.get("row_labels_sample")
    seen = len(sample) if isinstance(sample, list) else 0
    row_count = item.get("row_count")
    if isinstance(row_count, int):
        return row_count > seen
    return seen == 0


def _semantic(contract_context: Any) -> dict[str, Any]:
    if not isinstance(contract_context, dict):
        return {}
    semantic = contract_context.get("contrato_semantico", {})
    return semantic if isinstance(semantic, dict) else {}
