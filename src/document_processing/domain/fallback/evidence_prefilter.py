"""Pre-filtro deterministico da evidencia antes da selecao por LLM (fase 0).

Para cada requisito do contrato, deriva os termos de busca (nomes e sinonimos
do grupo de metricas, dos indicadores selecionados e das entidades de contexto)
e marca quais artefatos do inventario os contem. A LLM continua escolhendo, mas
entre candidatos; o validador recusa o que ficou fora.

Nenhum termo e conhecido pelo codigo: tudo sai do contrato. O resumo do
inventario mostra poucas linhas por tabela e nenhuma por grafico; quando ele nao
basta para decidir, o artefato completo (``schema`` + todas as ``rows``) e lido
por um carregador injetado pela aplicacao e a busca e refeita sobre o texto
inteiro. So quando nem isso e possivel (artefato ilegivel, sem carregador) o
artefato entra como candidato com o motivo ``amostra_incompleta`` — nunca se
exclui o que nao foi visto.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from document_processing.domain.contracts.mapping_requirements import (
    MappingRequirement,
    MappingRequirementsError,
    mapping_requirements_from_context,
)
from document_processing.domain.contracts.text_normalization import normalize_text

MIN_TERM_LENGTH = 3

FONTE_RESUMO = "resumo"
FONTE_ARTEFATO_COMPLETO = "artefato_completo"

# path do artefato -> texto normalizado do artefato inteiro, ou None se ilegivel.
ArtifactTextLoader = Callable[[str], str | None]


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
    fonte: str = FONTE_RESUMO  # onde o termo foi encontrado


@dataclass(frozen=True)
class PrefilterResult:
    """Candidatos por requisito e o que a leitura completa decidiu."""

    candidates: dict[str, list[ArtifactCandidate]]
    artefatos_lidos: tuple[str, ...] = ()  # lidos por completo (cache por path)
    excluidos_apos_leitura: tuple[str, ...] = ()  # lidos e candidatos de nenhum requisito
    sem_leitura: tuple[str, ...] = ()  # amostra incompleta e leitura indisponivel


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
    *,
    load_artifact_text: ArtifactTextLoader | None = None,
) -> dict[str, list[ArtifactCandidate]]:
    """requisito -> artefatos candidatos, na ordem do inventario."""
    return run_prefilter(
        inventory_items, contract_context, load_artifact_text=load_artifact_text
    ).candidates


def run_prefilter(
    inventory_items: list[Any],
    contract_context: Any,
    *,
    load_artifact_text: ArtifactTextLoader | None = None,
) -> PrefilterResult:
    """Pre-filtro em duas passadas: resumo do inventario e, se preciso, artefato inteiro.

    O artefato completo e lido no maximo uma vez por path, mesmo com varios
    requisitos; a leitura so acontece quando o resumo nao decide (amostra
    incompleta) e nenhum termo casou nele.
    """
    criteria = search_criteria_by_requirement(contract_context)
    full_text_cache: dict[str, str | None] = {}

    def full_text(path: str) -> str | None:
        if load_artifact_text is None:
            return None
        if path not in full_text_cache:
            try:
                full_text_cache[path] = load_artifact_text(path)
            except Exception:  # leitura e melhor esforco: sem texto, sem exclusao
                full_text_cache[path] = None
        return full_text_cache[path]

    result: dict[str, list[ArtifactCandidate]] = {}
    for requisito, spec in criteria.items():
        candidates: list[ArtifactCandidate] = []
        for item in inventory_items:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).strip("/")
            if not path:
                continue
            matched = _matched_terms(spec.termos, _item_text(item))
            if matched:
                candidates.append(ArtifactCandidate(path, "termo_casado", matched, FONTE_RESUMO))
                continue
            if not _sample_is_incomplete(item):
                continue
            text = full_text(path)
            if text is None:
                candidates.append(ArtifactCandidate(path, "amostra_incompleta"))
                continue
            matched = _matched_terms(spec.termos, text)
            if matched:
                candidates.append(
                    ArtifactCandidate(path, "termo_casado", matched, FONTE_ARTEFATO_COMPLETO)
                )
        result[requisito] = candidates

    lidos = tuple(path for path, text in full_text_cache.items() if text is not None)
    ainda_candidatos = {c.path for candidates in result.values() for c in candidates}
    return PrefilterResult(
        candidates=result,
        artefatos_lidos=lidos,
        excluidos_apos_leitura=tuple(p for p in lidos if p not in ainda_candidatos),
        sem_leitura=tuple(path for path, text in full_text_cache.items() if text is None),
    )


def artifact_full_text(artifact: Any, *, item: Any = None) -> str | None:
    """Texto de busca do artefato inteiro: nome, secao, cabecalhos e todas as celulas.

    Tabelas e graficos persistidos pela extracao tem a mesma forma
    (``name``, ``schema``, ``rows``); ``item`` e o registro do inventario, que
    traz o ``section_title`` que o arquivo nao repete.
    """
    if not isinstance(artifact, dict):
        return None
    rows = artifact.get("rows")
    if not isinstance(rows, list):
        return None
    parts: list[Any] = [artifact.get("name")]
    if isinstance(item, dict):
        parts.extend([item.get("name"), item.get("section_title")])
    schema = artifact.get("schema")
    if isinstance(schema, list):
        parts.extend(schema)
    for row in rows:
        if isinstance(row, list):
            parts.extend(row)
    return " | ".join(normalize_text(str(part)) for part in parts if part not in (None, ""))


def _matched_terms(terms: dict[str, str], text: str) -> tuple[str, ...]:
    return tuple(sorted(term for term in terms if term in text))


def prefilter_payload(prefiltered: dict[str, list[ArtifactCandidate]]) -> dict[str, Any]:
    """Forma serializavel: paths por requisito e a justificativa de cada um."""
    return {
        requisito: [
            {
                "path": candidate.path,
                "motivo": candidate.motivo,
                **({"fonte": candidate.fonte} if candidate.motivo == "termo_casado" else {}),
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
    """Texto do resumo do inventario (tabelas: amostra de rotulos; graficos: series e categorias)."""
    parts: list[Any] = [item.get("name"), item.get("section_title")]
    for key in ("schema", "row_labels_sample", "series_sample", "categories_sample"):
        values = item.get(key)
        if isinstance(values, list):
            parts.extend(values)
    return " | ".join(normalize_text(part) for part in parts if part is not None)


def _sample_is_incomplete(item: dict[str, Any]) -> bool:
    """O resumo mostrou todas as linhas? Sem ``row_count`` e sem amostra, nao se sabe.

    Graficos chegam sem rotulos de linha e tabelas trazem uma amostra curta; um
    artefato que nao foi visto inteiro so pode ser descartado depois de lido.
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
