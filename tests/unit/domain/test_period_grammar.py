"""Fase 2.3: interpretador generico de periodos, sem conhecimento de dominio."""

from __future__ import annotations

import pytest

from document_processing.domain.contracts.period_grammar import (
    Period,
    derive_period,
    expected_periods_by_role,
    parse_period_label,
    reference_attribute,
    strip_footnotes,
)

T = "trimestre"


@pytest.mark.parametrize(
    ("rotulo", "esperado"),
    [
        ("1T26", Period(T, 2026, 1)),
        ("1T2026", Period(T, 2026, 1)),
        ("2026-Q1", Period(T, 2026, 1)),
        ("Q1 2026", Period(T, 2026, 1)),
        ("1º T26", Period(T, 2026, 1)),
        ("4T25*", Period(T, 2025, 4)),
        ("2T26 (a)", Period(T, 2026, 2)),
        ("2T26¹", Period(T, 2026, 2)),
        ("1S26", Period("semestre", 2026, 1)),
        ("H1 2026", Period("semestre", 2026, 1)),
        ("mar/26", Period("mes", 2026, 3)),
        ("Jun/26", Period("mes", 2026, 6)),
        ("dez-25", Period("mes", 2025, 12)),
        ("03/2026", Period("mes", 2026, 3)),
        ("2025", Period("ano", 2025, 1)),
    ],
)
def test_rotulos_tolerantes_viram_o_mesmo_periodo(rotulo: str, esperado: Period) -> None:
    assert parse_period_label(rotulo) == esperado


@pytest.mark.parametrize(
    "rotulo",
    ["1T26 UDM*", "%T/T", "Consolidado 2T26", "Total", "# Und.", "", None, "5T26", "13/2026", "T"],
)
def test_texto_que_nao_e_inteiramente_um_periodo_nao_parseia(rotulo: object) -> None:
    assert parse_period_label(rotulo) is None


def test_notas_de_rodape_saem_e_sufixo_de_escopo_fica() -> None:
    assert strip_footnotes("2T26 (a)") == "2t26"
    assert strip_footnotes("1T26 UDM*") == "1t26 udm"


def test_anterior_e_mesmo_periodo_ano_anterior_com_virada_de_ano() -> None:
    assert Period(T, 2026, 1).anterior() == Period(T, 2025, 4)
    assert Period(T, 2026, 1).anterior(5) == Period(T, 2024, 4)
    assert Period(T, 2026, 1).mesmo_periodo_ano_anterior() == Period(T, 2025, 1)
    assert Period("mes", 2026, 1).anterior(2) == Period("mes", 2025, 11)
    assert Period("ano", 2026, 1).anterior() == Period("ano", 2025, 1)
    assert Period(T, 2026, 3).rotulo() == "3T26"


def test_indice_fora_do_escopo_e_recusado() -> None:
    with pytest.raises(ValueError):
        Period(T, 2026, 5)
    with pytest.raises(ValueError):
        Period("decada", 2026, 1)


def test_derivacao_conhecida_e_desconhecida() -> None:
    referencia = Period(T, 2026, 2)
    assert derive_period(referencia, {"origem": "identidade_documento.periodo"}) == referencia
    assert derive_period(referencia, {"relacao": "anterior", "passo": 1}) == Period(T, 2026, 1)
    assert derive_period(referencia, {"relacao": "mesmo_periodo_ano_anterior"}) == Period(T, 2025, 2)
    assert derive_period(referencia, {"relacao": "acumulado_12_meses"}) is None
    assert derive_period(referencia, {"relacao": "anterior", "passo": 0}) is None
    assert derive_period(referencia, None) is None
    assert derive_period(referencia, {}) is None


PAPEIS = {
    "periodo_referencia": {"origem": "identidade_documento.periodo"},
    "periodo_comparativo_anterior": {"relacao": "anterior", "passo": 1},
    "mesmo_periodo_ano_anterior": {"relacao": "mesmo_periodo_ano_anterior"},
}


def test_periodos_esperados_por_papel_a_partir_da_identidade() -> None:
    assert reference_attribute(PAPEIS.values()) == "periodo"
    esperados = expected_periods_by_role(PAPEIS, {"entidade": "cury", "periodo": "2T26"})
    assert esperados == {
        "periodo_referencia": Period(T, 2026, 2),
        "periodo_comparativo_anterior": Period(T, 2026, 1),
        "mesmo_periodo_ano_anterior": Period(T, 2025, 2),
    }


def test_sem_identidade_legivel_nada_e_derivado() -> None:
    assert expected_periods_by_role(PAPEIS, {"entidade": "cyre3", "periodo": "sem_periodo"}) == {}
    assert expected_periods_by_role(PAPEIS, {"entidade": "eztc3"}) == {}
    sem_origem = {"periodo_comparativo_anterior": {"relacao": "anterior", "passo": 1}}
    assert expected_periods_by_role(sem_origem, {"periodo": "2T26"}) == {}
