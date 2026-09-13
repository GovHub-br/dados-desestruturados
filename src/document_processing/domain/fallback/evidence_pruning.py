"""Poda de evidencia superflua antes da chamada de mapeamento.

Cada artefato levado a LLM custa duas vezes: ocupa a entrada e alonga o
raciocinio, que divide o mesmo teto com a resposta. Mas podar por semantica e
perigoso: ha documentos em que o artefato correto nao carrega nenhum termo do
indicador — no Itau 2T26, o grafico de NPL se chama apenas "Qualidade do
credito" e nao menciona inadimplencia em lugar nenhum.

Por isso a regra aqui e conservadora e so descarta quando ha prova de que o
descarte e seguro: a evidencia generica sai apenas quando a evidencia especifica
ja cobre, sozinha, todos os indicadores obrigatorios da unidade. Se faltar um
unico indicador, nada e descartado.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


def normalize_term(value: Any) -> str:
    """Reduz um rotulo a letras e digitos minusculos, sem acento nem separador.

    A extracao cola palavras ("MargemFinanceira Gerencial"), entao comparar por
    espaco perderia correspondencias legitimas.
    """
    texto = unicodedata.normalize("NFKD", str(value))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    return re.sub(r"[^0-9a-z]+", "", texto.casefold())


def _unit_metric_groups(
    scoped_contract: dict[str, Any], unit_root: str
) -> list[dict[str, Any]]:
    """Isola os grupos de metrica da unidade.

    O contrato escopado por unidade preserva os dois grupos, entao filtrar aqui
    e o que impede exigir de uma unidade percentual os indicadores monetarios.
    """
    semantic = scoped_contract.get("contrato_semantico", {})
    metrics = semantic.get("metricas", {}) if isinstance(semantic, dict) else {}
    if not isinstance(metrics, dict):
        return []
    raiz = str(unit_root).strip()
    selecionados = [
        grupo
        for chave, grupo in metrics.items()
        if isinstance(grupo, dict) and (not raiz or str(chave) == raiz)
    ]
    # Contrato sem grupo homonimo a raiz: usar todos e mais seguro que nenhum,
    # porque a poda so descarta quando a cobertura obrigatoria esta completa.
    if not selecionados and not raiz:
        return [g for g in metrics.values() if isinstance(g, dict)]
    return selecionados


def indicator_terms(
    scoped_contract: dict[str, Any], unit_root: str = ""
) -> dict[str, set[str]]:
    """Mapeia indicador -> termos normalizados que o identificam no documento."""
    termos: dict[str, set[str]] = {}
    for grupo in _unit_metric_groups(scoped_contract, unit_root):
        indicadores = grupo.get("indicadores") if isinstance(grupo, dict) else None
        if not isinstance(indicadores, dict):
            continue
        for nome, definicao in indicadores.items():
            candidatos = {str(nome), str(nome).replace("_", " ")}
            if isinstance(definicao, dict):
                candidatos.update(str(s) for s in definicao.get("sinonimos", []) or [])
            normalizados = {normalize_term(c) for c in candidatos}
            termos[str(nome)] = {t for t in normalizados if len(t) >= 3}
    return termos


def required_indicators(
    scoped_contract: dict[str, Any], unit_root: str = ""
) -> set[str]:
    """Indicadores que o contrato marca como obrigatorios na unidade."""
    obrigatorios: set[str] = set()
    for grupo in _unit_metric_groups(scoped_contract, unit_root):
        indicadores = grupo.get("indicadores") if isinstance(grupo, dict) else None
        if not isinstance(indicadores, dict):
            continue
        for nome, definicao in indicadores.items():
            if isinstance(definicao, dict) and definicao.get("obrigatorio") is True:
                obrigatorios.add(str(nome))
    return obrigatorios


def anchored_indicators(anchors: list[str], termos: dict[str, set[str]]) -> set[str]:
    """Indicadores que as ancoras verificadas de um artefato identificam."""
    normalizadas = [normalize_term(a) for a in anchors]
    encontrados: set[str] = set()
    for indicador, sinonimos in termos.items():
        if any(
            sinonimo and sinonimo in ancora
            for ancora in normalizadas
            for sinonimo in sinonimos
        ):
            encontrados.add(indicador)
    return encontrados


@dataclass(frozen=True)
class PruningDecision:
    """Resultado da poda, com o motivo, para virar artefato e metrica."""

    kept: tuple[str, ...]
    dropped: tuple[str, ...]
    reason: str

    @property
    def pruned(self) -> bool:
        return bool(self.dropped)


def prune_generic_evidence(
    *,
    anchors_by_artifact: dict[str, list[str]],
    scoped_contract: dict[str, Any],
    unit_root: str = "",
) -> PruningDecision:
    """Descarta evidencia generica somente quando a especifica ja cobre tudo."""
    todos = tuple(anchors_by_artifact)
    termos = indicator_terms(scoped_contract, unit_root)
    obrigatorios = required_indicators(scoped_contract, unit_root) & set(termos)
    if not obrigatorios:
        return PruningDecision(todos, (), "unidade sem indicador obrigatorio declarado")

    especificos: list[str] = []
    cobertos: set[str] = set()
    for caminho, ancoras in anchors_by_artifact.items():
        encontrados = anchored_indicators(list(ancoras or []), termos)
        if encontrados:
            especificos.append(caminho)
            cobertos |= encontrados

    faltando = obrigatorios - cobertos
    if faltando:
        return PruningDecision(
            todos,
            (),
            "evidencia especifica nao cobre "
            f"{sorted(faltando)}; nada descartado para nao perder a fonte correta",
        )
    descartados = tuple(c for c in todos if c not in set(especificos))
    if not descartados:
        return PruningDecision(todos, (), "nenhuma evidencia generica a descartar")
    return PruningDecision(
        tuple(especificos),
        descartados,
        "evidencia especifica cobre todos os indicadores obrigatorios "
        f"({sorted(obrigatorios)}); generica descartada",
    )
