"""Testes da poda de evidencia por afinidade com a unidade.

O caso que governa o desenho: no Itau 2T26 o grafico correto de inadimplencia
nao carrega nenhum termo do indicador, so o titulo "Qualidade do credito". Uma
poda semantica ingenua apagaria justamente a fonte certa, entao a regra so
descarta quando a evidencia especifica ja cobre todos os obrigatorios.
"""

from __future__ import annotations

from document_processing.domain.fallback.evidence_pruning import (
    normalize_term,
    prune_generic_evidence,
)


def _contrato(**obrigatorios: bool) -> dict:
    return {
        "contrato_semantico": {
            "metricas": {
                "indicadores_monetarios": {
                    "indicadores": {
                        "margem_financeira": {
                            "sinonimos": ["Margem Financeira Gerencial"],
                            "obrigatorio": obrigatorios.get("margem", True),
                        },
                        "carteira_de_credito": {
                            "sinonimos": ["Carteira de credito"],
                            "obrigatorio": obrigatorios.get("carteira", True),
                        },
                    }
                },
                "indicadores_percentuais": {
                    "indicadores": {
                        "inadimplencia_90_dias": {
                            "sinonimos": ["NPL acima de 90 dias"],
                            "obrigatorio": True,
                        }
                    }
                },
            }
        }
    }


def test_extracao_cola_palavras_e_ainda_casa():
    """A extracao devolve 'MargemFinanceira Gerencial'; comparar por espaco perderia."""
    assert normalize_term("MargemFinanceira Gerencial") == normalize_term(
        "Margem Financeira Gerencial"
    )


def test_descarta_generico_quando_especifico_cobre_tudo():
    decisao = prune_generic_evidence(
        anchors_by_artifact={
            "tables/table007.json": ["MargemFinanceira Gerencial"],
            "tables/table002.json": ["Carteira de crédito"],
            "charts/chart002.json": ["Qualidade do crédito"],
            "charts/chart005.json": ["Qualidade e custo do crédito"],
        },
        scoped_contract=_contrato(),
        unit_root="indicadores_monetarios",
    )
    assert set(decisao.kept) == {"tables/table007.json", "tables/table002.json"}
    assert set(decisao.dropped) == {"charts/chart002.json", "charts/chart005.json"}


def test_nao_descarta_nada_quando_falta_cobrir_um_obrigatorio():
    """O caso do Itau: a unica fonte de NPL nao se identifica por termo algum."""
    decisao = prune_generic_evidence(
        anchors_by_artifact={
            "charts/chart002.json": ["Qualidade do crédito"],
            "charts/chart004.json": ["Qualidade do crédito"],
        },
        scoped_contract=_contrato(),
        unit_root="indicadores_percentuais",
    )
    assert decisao.pruned is False
    assert set(decisao.kept) == {"charts/chart002.json", "charts/chart004.json"}
    assert "inadimplencia_90_dias" in decisao.reason


def test_unidade_percentual_nao_exige_indicador_monetario():
    """O contrato escopado ainda traz os dois grupos; a raiz e que recorta."""
    decisao = prune_generic_evidence(
        anchors_by_artifact={
            "charts/chart006.json": ["NPL acima de 90 dias"],
            "charts/chart003.json": ["Qualidade do crédito"],
        },
        scoped_contract=_contrato(),
        unit_root="indicadores_percentuais",
    )
    assert set(decisao.kept) == {"charts/chart006.json"}
    assert set(decisao.dropped) == {"charts/chart003.json"}


def test_sem_indicador_obrigatorio_nada_e_descartado():
    decisao = prune_generic_evidence(
        anchors_by_artifact={"charts/chart002.json": ["Qualidade do crédito"]},
        scoped_contract=_contrato(margem=False, carteira=False),
        unit_root="indicadores_monetarios",
    )
    assert decisao.pruned is False
