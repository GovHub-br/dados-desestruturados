"""Fase 1 do plano da assinatura de layout: enumerar as entradas-alvo.

O contrato ja diz tudo o que a LLM adivinhava ao montar as chaves do
``mapeamento_canonico``: quais requisitos existem, quantas observacoes cada um
tem, quais campos de contexto acompanham cada observacao, qual chave identifica
cada array e de onde vem o valor do filtro (``chaves_de_item.origem_valor``).
Este modulo transforma isso numa lista fechada de chaves. A LLM preenche as
chaves prontas; o validador compara chave a chave.

O que fica com a LLM e somente o filtro cujo valor so o documento conhece
(``origem_valor = evidencia``): a entrada sai com o marcador ``<evidencia>`` e
a LLM cria uma instancia por rotulo lido no artefato.

Nenhum nome de campo, papel ou rotulo de um dominio aparece aqui: tudo vem do
contrato relevante e da identidade do documento recebida pelo chamador.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from document_processing.domain.contracts.capabilities import (
    ContractCapabilitiesError,
    derived_paths,
    item_key_specs,
)
from document_processing.domain.contracts.mapping_requirements import (
    MappingRequirement,
    MappingRequirementsError,
    mapping_requirements_from_context,
)
from document_processing.domain.contracts.schema import (
    contract_literal_paths,
    schema_array_paths,
    schema_paths,
)
from document_processing.domain.layouts.paths import parse_mapping_path

ORIGEM_IDENTIDADE = "identidade_documento"
ORIGEM_SELETOR = "seletor_observacao"
ORIGEM_EVIDENCIA = "evidencia"
# Marcadores que a LLM substitui; nunca podem sobreviver numa chave final.
MARCADOR_EVIDENCIA = "<evidencia>"
MARCADOR_CHAVE = "<chave>"
# Valores que nunca sao um filtro valido: sao nomes de origem, nao rotulos.
VALORES_PROIBIDOS_EM_FILTRO = frozenset(
    {MARCADOR_EVIDENCIA, MARCADOR_CHAVE, ORIGEM_IDENTIDADE, ORIGEM_SELETOR, ORIGEM_EVIDENCIA}
)
# Atributo da identidade usado quando o contrato nao nomeia outro: quem e o
# documento. ``periodo`` e o outro atributo conhecido; um contrato pode
# apontar qualquer um deles em ``chaves_de_item.<path>.atributo_identidade``.
ATRIBUTO_IDENTIDADE_PADRAO = "entidade"

PapelNoAlvo = Literal["valor", "contexto", "livre"]
ModoArray = Literal["item", "colecao"]


class TargetEnumerationError(RuntimeError):
    """O contrato ou a identidade nao permitem fechar a lista de chaves."""


@dataclass(frozen=True)
class ArrayFilter:
    """Filtro ``[chave=valor]`` de um array atravessado por uma entrada."""

    array: str
    chave: str | None
    valor: str | None
    origem: str | None

    @property
    def pendente(self) -> bool:
        """Verdadeiro quando o valor (ou a propria chave) fica com a LLM."""
        return self.valor is None

    def render(self) -> str:
        return f"[{self.chave or MARCADOR_CHAVE}={self.valor or MARCADOR_EVIDENCIA}]"


@dataclass(frozen=True)
class TargetEntry:
    """Uma chave do ``mapeamento_canonico`` que o contrato exige ou admite."""

    chave: str
    path_normalizado: str
    requisito: str
    seletores: dict[str, str]
    papel_no_alvo: PapelNoAlvo
    campo: str
    obrigatorio: bool
    modo_array: ModoArray
    filtros: tuple[ArrayFilter, ...] = ()

    @property
    def filtros_pendentes(self) -> tuple[str, ...]:
        return tuple(item.array for item in self.filtros if item.pendente)

    def matches(self, mapping_key: str) -> bool:
        """Diz se uma chave gerada e esta entrada (exata, ou instancia de uma pendente)."""
        try:
            tokens = parse_mapping_path(mapping_key)
        except ValueError:
            return False
        path = ".".join(str(token["field"]) for token in tokens)
        if path != self.path_normalizado:
            return False
        filters_by_array: dict[str, tuple[str, str]] = {}
        cumulative: list[str] = []
        for token in tokens:
            cumulative.append(str(token["field"]))
            selector = token.get("selector")
            if selector is not None:
                filters_by_array[".".join(cumulative)] = (str(selector[0]), str(selector[1]))
        expected_arrays = {item.array for item in self.filtros}
        if set(filters_by_array) != expected_arrays:
            return False
        for expected in self.filtros:
            used_key, used_value = filters_by_array[expected.array]
            if not expected.pendente:
                if (used_key, used_value) != (expected.chave, expected.valor):
                    return False
                continue
            if expected.chave is not None and used_key != expected.chave:
                return False
            if used_value.strip() in VALORES_PROIBIDOS_EM_FILTRO or not used_value.strip():
                return False
        return True

    def payload(self) -> dict[str, Any]:
        """Forma enviada a LLM: compacta, sem nada que ela nao precise copiar."""
        item: dict[str, Any] = {
            "chave": self.chave,
            "requisito": self.requisito,
            "campo": self.campo,
            "papel_no_alvo": self.papel_no_alvo,
            "obrigatorio": self.obrigatorio,
            "modo_array": self.modo_array,
        }
        if self.seletores:
            item["seletores"] = dict(self.seletores)
        pending = {
            filtro.array: filtro.chave or MARCADOR_CHAVE
            for filtro in self.filtros
            if filtro.pendente
        }
        if pending:
            item["filtros_pendentes"] = pending
        return item


@dataclass(frozen=True)
class _Structure:
    allowed_paths: set[str]
    array_paths: set[str]
    item_keys: dict[str, str]
    key_origins: dict[str, str]
    identity_attributes: dict[str, str]
    derived_paths: set[str]
    requirements: list[MappingRequirement]


def _structure(contract_context: Mapping[str, Any]) -> _Structure:
    """Le a estrutura do recorte projetado ou do contrato bruto, sem distinguir o resto."""
    if not isinstance(contract_context, Mapping):
        raise TargetEnumerationError("Contexto do contrato semantico invalido.")
    projected = contract_context.get("estrutura_schema_saida")
    try:
        if isinstance(projected, Mapping):
            requirements = mapping_requirements_from_context(dict(contract_context))
            return _Structure(
                allowed_paths=_clean_set(projected.get("paths_permitidos")),
                array_paths=_clean_set(projected.get("arrays_que_exigem_seletor")),
                item_keys=_clean_map(projected.get("chaves_de_item")),
                key_origins=_clean_map(projected.get("origem_das_chaves")),
                identity_attributes=_clean_map(projected.get("atributos_identidade")),
                derived_paths=_clean_set(projected.get("paths_derivados")),
                requirements=requirements,
            )
        schema_saida = contract_context.get("schema_saida")
        if schema_saida is None:
            raise TargetEnumerationError(
                "Contexto do contrato sem estrutura_schema_saida nem schema_saida."
            )
        contract = dict(contract_context)
        specs = item_key_specs(contract)
        fixed = set(contract_literal_paths(schema_saida))
        return _Structure(
            allowed_paths=schema_paths(schema_saida) - fixed,
            array_paths=schema_array_paths(schema_saida),
            item_keys={path: spec.chave for path, spec in specs.items()},
            key_origins={
                path: spec.origem_valor for path, spec in specs.items() if spec.origem_valor
            },
            identity_attributes={
                path: spec.atributo_identidade
                for path, spec in specs.items()
                if spec.atributo_identidade
            },
            derived_paths=derived_paths(contract),
            requirements=mapping_requirements_from_context(
                contract, validate_schema_paths=False
            ),
        )
    except (MappingRequirementsError, ContractCapabilitiesError) as exc:
        raise TargetEnumerationError(str(exc)) from exc


def _clean_set(raw: Any) -> set[str]:
    if not isinstance(raw, list):
        return set()
    return {str(item).strip() for item in raw if str(item).strip()}


def _clean_map(raw: Any) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        return {}
    return {
        str(key).strip(): str(value).strip()
        for key, value in raw.items()
        if str(key).strip() and str(value).strip()
    }


def _arrays_on_path(path: str, array_paths: set[str], *, include_self: bool) -> list[str]:
    """Arrays atravessados pelo path, do mais externo ao mais interno."""
    found = [
        array
        for array in array_paths
        if path.startswith(f"{array}.") or (include_self and array == path)
    ]
    return sorted(found, key=len)


def _identity_value(
    *,
    array: str,
    chave: str,
    structure: _Structure,
    document_identity: Mapping[str, str],
) -> str:
    attribute = structure.identity_attributes.get(array)
    if attribute is None:
        attribute = chave if chave in document_identity else ATRIBUTO_IDENTIDADE_PADRAO
    value = str(document_identity.get(attribute, "")).strip()
    if not value:
        raise TargetEnumerationError(
            f"O array {array} filtra por '{chave}' com origem {ORIGEM_IDENTIDADE}, mas a "
            f"identidade do documento nao traz o atributo '{attribute}'. Atributos "
            f"recebidos: {sorted(document_identity)}."
        )
    return value


def _filters_for(
    *,
    requirement_path: str,
    arrays: list[str],
    selectors: Mapping[str, str],
    structure: _Structure,
    document_identity: Mapping[str, str],
) -> tuple[ArrayFilter, ...]:
    """Um filtro por array do path; seletores da observacao vao para o array certo."""
    remaining = dict(selectors)
    filters: list[ArrayFilter] = []
    undeclared: list[int] = []
    for array in arrays:
        chave = structure.item_keys.get(array)
        origem = structure.key_origins.get(array)
        if chave is None:
            undeclared.append(len(filters))
            filters.append(ArrayFilter(array, None, None, None))
            continue
        if chave in remaining:
            filters.append(ArrayFilter(array, chave, remaining.pop(chave), ORIGEM_SELETOR))
            continue
        if origem == ORIGEM_SELETOR:
            raise TargetEnumerationError(
                f"O array {array} e identificado por '{chave}' com origem {ORIGEM_SELETOR}, "
                f"mas a observacao de {requirement_path} nao declara esse seletor: "
                f"{dict(selectors)}."
            )
        if origem == ORIGEM_IDENTIDADE:
            value = _identity_value(
                array=array, chave=chave, structure=structure, document_identity=document_identity
            )
            filters.append(ArrayFilter(array, chave, value, ORIGEM_IDENTIDADE))
            continue
        # evidencia, ou chave declarada sem origem: o valor fica com a LLM.
        filters.append(ArrayFilter(array, chave, None, origem or ORIGEM_EVIDENCIA))
    if remaining:
        # Contrato legado (arrays sem chave declarada): o seletor da observacao e o
        # filtro do array mais interno sem chave, como o resolvedor sempre leu.
        if len(remaining) != 1 or not undeclared:
            raise TargetEnumerationError(
                f"Seletores {sorted(remaining)} da observacao de {requirement_path} nao "
                "identificam nenhum array do path (chaves_de_item nao os declara)."
            )
        position = undeclared[-1]
        (key, value), = remaining.items()
        filters[position] = ArrayFilter(filters[position].array, key, value, ORIGEM_SELETOR)
    return tuple(filters)


def _render_key(path: str, filters: tuple[ArrayFilter, ...]) -> str:
    by_array = {item.array: item for item in filters}
    parts: list[str] = []
    cumulative: list[str] = []
    for field in path.split("."):
        cumulative.append(field)
        current = ".".join(cumulative)
        filtro = by_array.get(current)
        parts.append(field + (filtro.render() if filtro else ""))
    return ".".join(parts)


def enumerate_target_entries(
    *,
    contract_context: Mapping[str, Any],
    document_identity: Mapping[str, str],
) -> list[TargetEntry]:
    """Lista fechada de chaves que o candidato deve (ou pode) conter.

    ``contract_context`` e o recorte ``contrato_semantico_relevante`` (com
    ``estrutura_schema_saida``) ou o contrato bruto. ``document_identity`` traz
    ``entidade`` (o slug operacional) e, quando conhecido, ``periodo``.
    """
    structure = _structure(contract_context)
    entries: list[TargetEntry] = []
    covered_paths: set[str] = set()
    for requirement in structure.requirements:
        covered_paths.add(requirement.path)
        parent = requirement.path.rpartition(".")[0]
        is_array = requirement.path in structure.array_paths
        if not requirement.observations:
            # 1.7: requisito cujo path e o proprio array -> colecao inteira por linhas.
            arrays = _arrays_on_path(requirement.path, structure.array_paths, include_self=False)
            filters = _filters_for(
                requirement_path=requirement.path,
                arrays=arrays,
                selectors={},
                structure=structure,
                document_identity=document_identity,
            )
            entries.append(
                TargetEntry(
                    chave=_render_key(requirement.path, filters),
                    path_normalizado=requirement.path,
                    requisito=requirement.path,
                    seletores={},
                    papel_no_alvo="valor",
                    campo=requirement.path.rpartition(".")[2],
                    obrigatorio=True,
                    modo_array="colecao" if is_array else "item",
                    filtros=filters,
                )
            )
            continue
        arrays = _arrays_on_path(requirement.path, structure.array_paths, include_self=True)
        for observation in requirement.observations:
            filters = _filters_for(
                requirement_path=requirement.path,
                arrays=arrays,
                selectors=observation.selectors,
                structure=structure,
                document_identity=document_identity,
            )
            entries.append(
                TargetEntry(
                    chave=_render_key(requirement.path, filters),
                    path_normalizado=requirement.path,
                    requisito=requirement.path,
                    seletores=dict(observation.selectors),
                    papel_no_alvo="valor",
                    campo=requirement.path.rpartition(".")[2],
                    obrigatorio=observation.required,
                    modo_array="item",
                    filtros=filters,
                )
            )
            # 1.3: um irmao por campo de contexto dinamico, com os mesmos filtros.
            for field in observation.context_fields:
                context_path = f"{parent}.{field}"
                if context_path not in structure.allowed_paths:
                    continue
                covered_paths.add(context_path)
                entries.append(
                    TargetEntry(
                        chave=_render_key(context_path, filters),
                        path_normalizado=context_path,
                        requisito=requirement.path,
                        seletores=dict(observation.selectors),
                        papel_no_alvo="contexto",
                        campo=field,
                        obrigatorio=observation.required,
                        modo_array="item",
                        filtros=filters,
                    )
                )
    # 1.6: folhas dinamicas fora de arrays que nem o contrato deriva nem a DAG fixa
    # continuam mapeaveis, mas com chave fechada e sempre opcionais.
    for path in sorted(_free_leaf_paths(structure) - covered_paths):
        entries.append(
            TargetEntry(
                chave=path,
                path_normalizado=path,
                requisito=path,
                seletores={},
                papel_no_alvo="livre",
                campo=path.rpartition(".")[2],
                obrigatorio=False,
                modo_array="item",
            )
        )
    _assert_unique(entries)
    return entries


def _free_leaf_paths(structure: _Structure) -> set[str]:
    leaves = {
        path
        for path in structure.allowed_paths
        if path not in structure.array_paths
        and not any(other.startswith(f"{path}.") for other in structure.allowed_paths)
    }
    return {
        path
        for path in leaves
        if path not in structure.derived_paths
        and not any(path.startswith(f"{array}.") for array in structure.array_paths)
    }


def _assert_unique(entries: list[TargetEntry]) -> None:
    seen: set[str] = set()
    for entry in entries:
        if entry.chave in seen:
            raise TargetEnumerationError(
                f"O contrato produz a mesma chave para duas observacoes: {entry.chave}. "
                "Duas observacoes do mesmo requisito precisam de seletores distintos."
            )
        seen.add(entry.chave)


def expected_entries_payload(entries: list[TargetEntry]) -> list[dict[str, Any]]:
    return [entry.payload() for entry in entries]


@dataclass(frozen=True)
class EntryMatch:
    """Resultado de comparar as chaves geradas com as entradas esperadas."""

    por_chave: dict[str, TargetEntry | None]
    nao_esperadas: tuple[str, ...]
    obrigatorias_sem_chave: tuple[TargetEntry, ...]

    @property
    def cobertas(self) -> set[str]:
        return {entry.chave for entry in self.por_chave.values() if entry is not None}


def match_mapping_keys(entries: list[TargetEntry], mapping_keys: list[str]) -> EntryMatch:
    """Casa cada chave gerada com uma entrada; pendentes aceitam varias instancias."""
    por_chave: dict[str, TargetEntry | None] = {}
    for key in mapping_keys:
        por_chave[key] = next((entry for entry in entries if entry.matches(key)), None)
    covered = {entry.chave for entry in por_chave.values() if entry is not None}
    return EntryMatch(
        por_chave=por_chave,
        nao_esperadas=tuple(key for key, entry in por_chave.items() if entry is None),
        obrigatorias_sem_chave=tuple(
            entry for entry in entries if entry.obrigatorio and entry.chave not in covered
        ),
    )


def describe_unexpected_key(key: str, entries: list[TargetEntry]) -> str:
    """Diz, em linguagem de chave, o que a LLM deveria ter escrito no lugar."""
    try:
        path = ".".join(str(token["field"]) for token in parse_mapping_path(key))
    except ValueError:
        return f"'{key}' nao e um caminho valido e nao esta em entradas_esperadas."
    same_path = [entry.chave for entry in entries if entry.path_normalizado == path]
    if same_path:
        return (
            f"'{key}' nao esta em entradas_esperadas; para o campo {path} as chaves "
            f"esperadas sao {same_path} (copie-as exatamente, substituindo apenas "
            f"{MARCADOR_EVIDENCIA} pelo rotulo lido no artefato)."
        )
    return (
        f"'{key}' nao esta em entradas_esperadas: o campo {path} nao e requisito do "
        "contrato ou e preenchido deterministicamente pela DAG 2 (valor fixo, derivacao "
        "ou chave de item). Remova a chave."
    )
