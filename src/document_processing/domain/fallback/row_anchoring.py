"""Fase 3.2 do plano da assinatura de layout: ancorar a linha por sinonimo do contrato.

Hoje quem escolhe, entre linhas de rotulo parecido (ex.: "Vendas Contratadas
Brutas" vs. "Vendas Liquidas 100%"), qual e a linha pedida, e a LLM lendo o
rotulo livremente — e ela erra sem padrao (`__r2` reproduz o mesmo payload e
devolve respostas diferentes). Os sinonimos por indicador ja existem no
contrato (usados pelo pre-filtro da fase 0); aqui eles servem para resolver a
linha por codigo sempre que casarem uma unica linha, entre as tabelas ja
carregadas para a unidade. Sem match unico, a decisao continua sendo da LLM
(residuo) — nada muda para ela.

A coluna de rotulo vem da Fase 2 (``table_structure``) quando o chamador a
informa em ``label_columns``; sem ela, vale a coluna 0 — o mesmo default que o
exemplo de schema do prompt ja usa (``seletor_linha.coluna_rotulo``). Graficos
(sem ``rows``) nao entram aqui.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

from document_processing.domain.fallback.evidence_pruning import normalize_term

COLUNA_ROTULO_PADRAO = 0
_TAMANHO_MINIMO_SINONIMO = 3


@dataclass(frozen=True)
class ResolvedRowAnchor:
    """Linha unica encontrada por sinonimo, entre as tabelas candidatas."""

    arquivo_origem: str
    rotulo_linha: str
    indice_linha: int

    def payload(self) -> dict[str, Any]:
        return {
            "arquivo_origem": self.arquivo_origem,
            "rotulo_linha": self.rotulo_linha,
            "indice_linha": self.indice_linha,
        }


def _synonyms_from_definition(nome: str, definicao: Any) -> set[str]:
    candidatos = {str(nome), str(nome).replace("_", " ")}
    if isinstance(definicao, Mapping):
        candidatos.update(str(s) for s in definicao.get("sinonimos", []) or [])
    return candidatos


def indicator_synonyms_for_entry(
    *,
    requisito: str,
    seletores: Mapping[str, str],
    metric_groups: Mapping[str, Any],
) -> set[str]:
    """Sinonimos do indicador que esta entrada representa, quando ha um so candidato.

    Bancos: o indicador e um seletor da propria observacao
    (``seletores["indicador"]``) — procurado em qualquer grupo, pelo nome.
    Construtoras: o indicador mora dentro de um grupo cujo nome e um segmento
    do path do requisito (``vendas``/``lancamentos``); so resolve quando esse
    grupo declara exatamente um indicador (senao a escolha entre eles
    continua sendo da LLM).
    """
    indicador_selecionado = str(seletores.get("indicador", "")).strip()
    if indicador_selecionado:
        for group in metric_groups.values():
            indicadores = group.get("indicadores") if isinstance(group, Mapping) else None
            if isinstance(indicadores, Mapping) and indicador_selecionado in indicadores:
                return _synonyms_from_definition(
                    indicador_selecionado, indicadores[indicador_selecionado]
                )
        return set()

    segments = set(requisito.split("."))
    for group_name, group in metric_groups.items():
        if str(group_name) not in segments:
            continue
        indicadores = group.get("indicadores") if isinstance(group, Mapping) else None
        if isinstance(indicadores, Mapping) and len(indicadores) == 1:
            ((nome, definicao),) = indicadores.items()
            return _synonyms_from_definition(nome, definicao)
    return set()


def _row_label(row: Any, coluna_rotulo: int = COLUNA_ROTULO_PADRAO) -> str | None:
    if not isinstance(row, (list, tuple)) or coluna_rotulo >= len(row):
        return None
    label = str(row[coluna_rotulo]).strip()
    return label or None


def resolve_row_anchor(
    *,
    synonyms: Collection[str],
    tables: Mapping[str, Any],
    label_columns: Mapping[str, int] | None = None,
) -> ResolvedRowAnchor | None:
    """Acha a linha unica, entre as tabelas ja carregadas, cujo rotulo casa um sinonimo.

    ``tables`` mapeia path do artefato -> conteudo JSON ja carregado para a
    unidade (so entram os que tem ``rows``; graficos ficam de fora).
    ``label_columns`` (path -> coluna de rotulo lida pela Fase 2) substitui o
    default 0 onde existir. Sem sinonimo declarado, sem nenhuma linha casando,
    ou com mais de uma, devolve ``None`` — ambiguidade fica com a LLM, nunca
    resolvida por adivinhacao.
    """
    normalizados = {normalize_term(s) for s in synonyms if str(s).strip()}
    normalizados = {s for s in normalizados if len(s) >= _TAMANHO_MINIMO_SINONIMO}
    if not normalizados:
        return None

    encontrados: list[ResolvedRowAnchor] = []
    for path, artifact in tables.items():
        if not isinstance(artifact, Mapping):
            continue
        rows = artifact.get("rows")
        if not isinstance(rows, list):
            continue
        coluna_rotulo = (label_columns or {}).get(path, COLUNA_ROTULO_PADRAO)
        for index, row in enumerate(rows):
            label = _row_label(row, coluna_rotulo)
            if label is None:
                continue
            normalized_label = normalize_term(label)
            if any(sinonimo in normalized_label for sinonimo in normalizados):
                encontrados.append(
                    ResolvedRowAnchor(arquivo_origem=path, rotulo_linha=label, indice_linha=index)
                )
    if len(encontrados) == 1:
        return encontrados[0]
    return None
