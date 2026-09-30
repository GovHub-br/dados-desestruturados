"""Fase 2.3 do plano da assinatura de layout: papel por coluna resolvido pelo contrato.

Quando o contrato declara ``papeis.<seletor>.<papel>.derivacao`` e a
identidade do documento traz o atributo de origem (``identidade_documento.periodo``),
o codigo calcula o periodo esperado por papel e casa com os cabecalhos da tabela.
Uma coluna so recebe um papel quando o cabecalho inteiro e aquele periodo e
nenhuma outra coluna e o mesmo periodo — "1T26 UDM*" nao e "1T26", e duas
colunas "2T26" na mesma tabela deixam o papel sem resolucao. Tudo que nao
resolve continua com a LLM (camada (b) do plano), sem adivinhacao.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from document_processing.domain.contracts.mapping_requirements import (
    role_derivations_from_context,
)
from document_processing.domain.contracts.period_grammar import (
    Period,
    expected_periods_by_role,
    parse_period_label,
)
from document_processing.domain.fallback.table_structure import (
    TableStructure,
    read_table_structure,
)

ORIGEM_CONTRATO = "contrato"


@dataclass(frozen=True)
class ColumnRoleResolution:
    """Papeis de um seletor casados com colunas de uma tabela."""

    seletor: str
    papel_por_coluna: dict[int, str] = field(default_factory=dict)
    ambiguos: tuple[str, ...] = ()
    ausentes: tuple[str, ...] = ()

    def coluna_do_papel(self, papel: str) -> int | None:
        for coluna, nome in self.papel_por_coluna.items():
            if nome == papel:
                return coluna
        return None

    def payload(self) -> dict[str, Any]:
        item: dict[str, Any] = {
            str(coluna): papel for coluna, papel in sorted(self.papel_por_coluna.items())
        }
        return item


@dataclass(frozen=True)
class TableAnalysis:
    """Estrutura de uma tabela mais os papeis por coluna que o contrato resolveu."""

    estrutura: TableStructure
    papeis: dict[str, ColumnRoleResolution] = field(default_factory=dict)

    def coluna_do_papel(self, seletor: str, papel: str) -> int | None:
        resolucao = self.papeis.get(seletor)
        return resolucao.coluna_do_papel(papel) if resolucao else None

    def payload(self) -> dict[str, Any]:
        item = self.estrutura.payload()
        resolvidos = {
            seletor: resolucao.payload()
            for seletor, resolucao in self.papeis.items()
            if resolucao.papel_por_coluna
        }
        if resolvidos:
            item["papel_por_coluna"] = resolvidos
            item["origem_papeis"] = ORIGEM_CONTRATO
        pendentes = {
            seletor: sorted(resolucao.ambiguos + resolucao.ausentes)
            for seletor, resolucao in self.papeis.items()
            if resolucao.ambiguos or resolucao.ausentes
        }
        if pendentes:
            item["papeis_nao_resolvidos"] = pendentes
        return item


def resolve_column_roles(
    structure: TableStructure,
    expected: Mapping[str, Period],
    *,
    seletor: str,
) -> ColumnRoleResolution:
    """Casa cada periodo esperado com a unica coluna cujo cabecalho e esse periodo."""
    colunas_por_periodo: dict[Period, list[int]] = {}
    for indice, cabecalho in enumerate(structure.cabecalhos):
        if indice == structure.coluna_rotulo:
            continue
        periodo = parse_period_label(cabecalho)
        if periodo is not None:
            colunas_por_periodo.setdefault(periodo, []).append(indice)
    papel_por_coluna: dict[int, str] = {}
    ambiguos: list[str] = []
    ausentes: list[str] = []
    for papel, periodo in expected.items():
        colunas = colunas_por_periodo.get(periodo, [])
        if len(colunas) == 1:
            papel_por_coluna[colunas[0]] = papel
        elif colunas:
            ambiguos.append(papel)
        else:
            ausentes.append(papel)
    return ColumnRoleResolution(
        seletor=seletor,
        papel_por_coluna=papel_por_coluna,
        ambiguos=tuple(ambiguos),
        ausentes=tuple(ausentes),
    )


def expected_periods_by_selector(
    contract_context: Mapping[str, Any],
    document_identity: Mapping[str, Any] | None,
) -> dict[str, dict[str, Period]]:
    """Periodo esperado por papel, para cada seletor cujo contrato declara derivacao."""
    if not document_identity:
        return {}
    esperados: dict[str, dict[str, Period]] = {}
    for seletor, roles in role_derivations_from_context(contract_context).items():
        periodos = expected_periods_by_role(roles, document_identity)
        if periodos:
            esperados[seletor] = periodos
    return esperados


def analyze_tables(
    loaded_artifacts: Mapping[str, Any] | None,
    *,
    contract_context: Mapping[str, Any],
    document_identity: Mapping[str, Any] | None,
) -> dict[str, TableAnalysis]:
    """Estrutura + papeis por coluna de cada artefato de tabela carregado."""
    esperados = expected_periods_by_selector(contract_context, document_identity)
    analyses: dict[str, TableAnalysis] = {}
    for path, artifact in (loaded_artifacts or {}).items():
        if not isinstance(artifact, Mapping):
            continue
        estrutura = read_table_structure(str(path), artifact)
        if estrutura is None:
            continue
        papeis = {
            seletor: resolve_column_roles(estrutura, periodos, seletor=seletor)
            for seletor, periodos in esperados.items()
        }
        analyses[str(path)] = TableAnalysis(estrutura=estrutura, papeis=papeis)
    return analyses


def label_columns(analyses: Mapping[str, TableAnalysis]) -> dict[str, int]:
    return {path: analysis.estrutura.coluna_rotulo for path, analysis in analyses.items()}
