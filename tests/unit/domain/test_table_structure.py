"""Fase 2: estrutura da tabela (2.1, 2.2, 2.4) e papel por coluna pelo contrato (2.3)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from document_processing.domain.contracts.period_grammar import Period, parse_period_label
from document_processing.domain.fallback.column_roles import (
    analyze_tables,
    expected_periods_by_selector,
    label_columns,
    resolve_column_roles,
)
from document_processing.domain.fallback.table_structure import Segment, read_table_structure

CONTRATOS = Path("infra/minio-bootstrap/contracts")
GABARITOS = Path("eval/gabaritos")

# Tabela real do Cury (1T26): cabecalho no schema, colunas UDM com sufixo de outro escopo.
TABELA_CURY = {
    "schema": ["Lançamentos", "1T26", "4T25", "%T/T", "1T25", "%A/A", "1T26 UDM*", "1T25 UDM*", "%A/A"],
    "rows": [
        ["Número de Empreendimentos", "10", "5", "100,0%", "14", "-28,6%", "33", "38", "-13,2%"],
        ["VGV (R$ milhões)", "2.646,8", "1.289,5", "105,3%", "2.783,5", "-4,9%", "8.147,9", "7.478,7", "8,9%"],
        ["Número de Unidades", "8.001", "3.833", "108,7%", "9.132", "-12,4%", "25.235", "23.938", "5,4%"],
    ],
}
IDENTIDADE_1T26 = {"entidade": "cury", "periodo": "1T26"}
PAPEIS = {
    "periodo_referencia": {"origem": "identidade_documento.periodo"},
    "periodo_comparativo_anterior": {"relacao": "anterior", "passo": 1},
    "mesmo_periodo_ano_anterior": {"relacao": "mesmo_periodo_ano_anterior"},
}


@pytest.fixture(scope="module")
def contrato_construtoras() -> dict[str, Any]:
    caminho = next((CONTRATOS / "construtoras" / "v1.9.1").glob("*.json"))
    return json.loads(caminho.read_text(encoding="utf-8"))


def test_schema_legivel_e_o_cabecalho_e_a_coluna_de_rotulo_e_a_textual() -> None:
    estrutura = read_table_structure("tables/t.json", TABELA_CURY)
    assert estrutura is not None
    assert estrutura.cabecalho_lido
    assert estrutura.linhas_cabecalho == ()
    assert estrutura.coluna_rotulo == 0
    assert estrutura.cabecalhos == tuple(TABELA_CURY["schema"])
    assert estrutura.rotulos_linha == ("Número de Empreendimentos", "VGV (R$ milhões)", "Número de Unidades")
    assert estrutura.rotulos_normalizados[2] == "numero de unidades"
    assert estrutura.segmentos == ()
    assert estrutura.linhas_de_dados() == (0, 1, 2)


def test_schema_generico_promove_a_primeira_linha_textual_a_cabecalho() -> None:
    tabela = {
        "schema": ["column_1", "column_2", "column_3", "column_4"],
        "rows": [
            ["", "2T26", "1T26", "2T25"],
            ["Unidades", "100", "90", "80"],
            ["VGV", "1,0", "0,9", "0,8"],
        ],
    }
    estrutura = read_table_structure("tables/t.json", tabela)
    assert estrutura is not None
    assert estrutura.cabecalho_lido
    assert estrutura.linhas_cabecalho == (0,)
    assert estrutura.cabecalhos == ("", "2T26", "1T26", "2T25")
    assert estrutura.linhas_de_dados() == (1, 2)


def test_schema_generico_sem_linha_de_cabecalho_fica_declarado_como_nao_lido() -> None:
    tabela = {"schema": ["column_1", "column_2"], "rows": [["Unidades", "100"], ["VGV", "1,0"]]}
    estrutura = read_table_structure("tables/t.json", tabela)
    assert estrutura is not None
    assert not estrutura.cabecalho_lido
    assert estrutura.payload()["cabecalho_lido"] is False


def test_coluna_de_rotulo_nao_e_a_primeira_quando_ela_e_numerica() -> None:
    tabela = {
        "schema": ["#", "Empresa", "2T26"],
        "rows": [["1", "Cury", "10"], ["2", "Tenda", "20"], ["3", "MRV", "30"]],
    }
    estrutura = read_table_structure("tables/t.json", tabela)
    assert estrutura is not None
    assert estrutura.coluna_rotulo == 1
    assert estrutura.rotulos_linha == ("Cury", "Tenda", "MRV")


def test_linhas_so_com_rotulo_viram_titulos_de_segmento() -> None:
    tabela = {
        "schema": ["", "2T26", "1T26"],
        "rows": [
            ["MRV", "", ""],
            ["Unidades", "9.841", "9.000"],
            ["Sensia", "", ""],
            ["Unidades", "545", "500"],
            ["TOTAL INCORPORACAO", "", ""],
            ["Unidades", "10.386", "9.500"],
        ],
    }
    estrutura = read_table_structure("tables/t.json", tabela)
    assert estrutura is not None
    assert estrutura.segmentos == (
        Segment("MRV", 1, 1),
        Segment("Sensia", 3, 3),
        Segment("TOTAL INCORPORACAO", 5, 5),
    )
    assert estrutura.linhas_de_dados() == (1, 3, 5)
    assert estrutura.payload()["segmentos"][0] == {"titulo": "MRV", "inicio": 1, "fim": 1}


def test_artefato_sem_rows_nao_tem_estrutura() -> None:
    assert read_table_structure("charts/c.json", {"schema": ["a"], "series": []}) is None
    assert read_table_structure("tables/t.json", {"rows": []}) is None


def test_papel_por_coluna_ignora_sufixo_de_outro_escopo() -> None:
    estrutura = read_table_structure("tables/t.json", TABELA_CURY)
    assert estrutura is not None
    esperados = {
        "periodo_referencia": Period("trimestre", 2026, 1),
        "periodo_comparativo_anterior": Period("trimestre", 2025, 4),
        "mesmo_periodo_ano_anterior": Period("trimestre", 2025, 1),
    }
    resolucao = resolve_column_roles(estrutura, esperados, seletor="papel_periodo")
    assert resolucao.papel_por_coluna == {
        1: "periodo_referencia",
        2: "periodo_comparativo_anterior",
        4: "mesmo_periodo_ano_anterior",
    }
    assert resolucao.coluna_do_papel("periodo_referencia") == 1
    assert resolucao.ambiguos == () and resolucao.ausentes == ()
    assert resolucao.payload() == {"1": "periodo_referencia", "2": "periodo_comparativo_anterior", "4": "mesmo_periodo_ano_anterior"}


def test_duas_colunas_com_o_mesmo_periodo_deixam_o_papel_sem_resolucao() -> None:
    tabela = {"schema": ["Indicador", "2T26", "2T26", "1T26"], "rows": [["Unidades", "1", "2", "3"]]}
    estrutura = read_table_structure("tables/t.json", tabela)
    assert estrutura is not None
    esperados = {
        "periodo_referencia": Period("trimestre", 2026, 2),
        "periodo_comparativo_anterior": Period("trimestre", 2026, 1),
        "mesmo_periodo_ano_anterior": Period("trimestre", 2025, 2),
    }
    resolucao = resolve_column_roles(estrutura, esperados, seletor="papel_periodo")
    assert resolucao.papel_por_coluna == {3: "periodo_comparativo_anterior"}
    assert resolucao.ambiguos == ("periodo_referencia",)
    assert resolucao.ausentes == ("mesmo_periodo_ano_anterior",)


def test_cabecalho_com_nota_de_rodape_casa_o_papel() -> None:
    tabela = {"schema": ["", "2T26 (a)", "1T26 (b)", "Var.", "2T25 (c)"], "rows": [["Unidades", "1", "2", "3", "4"]]}
    contexto = {"contrato_semantico": {"requisitos_mapeamento": {"papeis": {"papel_periodo": {p: {"descricao": p, "derivacao": d} for p, d in PAPEIS.items()}}}}}
    analyses = analyze_tables({"tables/t.json": tabela}, contract_context=contexto, document_identity={"periodo": "2T26"})
    assert analyses["tables/t.json"].coluna_do_papel("papel_periodo", "mesmo_periodo_ano_anterior") == 4
    assert analyses["tables/t.json"].payload()["papel_por_coluna"] == {
        "papel_periodo": {"1": "periodo_referencia", "2": "periodo_comparativo_anterior", "4": "mesmo_periodo_ano_anterior"}
    }
    assert analyses["tables/t.json"].payload()["origem_papeis"] == "contrato"


def test_contrato_construtoras_resolve_as_tres_colunas_no_cury(contrato_construtoras: dict[str, Any]) -> None:
    analyses = analyze_tables(
        {"tables/table001.json": TABELA_CURY, "charts/chart001.json": {"series": []}},
        contract_context=contrato_construtoras,
        document_identity=IDENTIDADE_1T26,
    )
    assert list(analyses) == ["tables/table001.json"]
    assert label_columns(analyses) == {"tables/table001.json": 0}
    analysis = analyses["tables/table001.json"]
    assert analysis.coluna_do_papel("papel_periodo", "periodo_referencia") == 1
    assert analysis.coluna_do_papel("papel_periodo", "periodo_comparativo_anterior") == 2
    assert analysis.coluna_do_papel("papel_periodo", "mesmo_periodo_ano_anterior") == 4
    assert "papeis_nao_resolvidos" not in analysis.payload()


def test_sem_periodo_na_identidade_nenhum_papel_e_resolvido(contrato_construtoras: dict[str, Any]) -> None:
    assert expected_periods_by_selector(contrato_construtoras, {"entidade": "cyre3", "periodo": "sem_periodo"}) == {}
    analyses = analyze_tables({"tables/t.json": TABELA_CURY}, contract_context=contrato_construtoras, document_identity={"entidade": "eztc3"})
    assert analyses["tables/t.json"].papeis == {}
    assert "papel_por_coluna" not in analyses["tables/t.json"].payload()


def test_tabela_com_periodos_nas_linhas_nao_resolve_nada_pelo_cabecalho(contrato_construtoras: dict[str, Any]) -> None:
    """Caso EZTEC: cabecalho '# Und.', periodos como rotulos de linha — fica com a LLM."""
    tabela = {"schema": ["Periodo", "VGV", "# Und."], "rows": [["2T26", "10", "100"], ["1T26", "9", "90"]]}
    analyses = analyze_tables({"tables/t.json": tabela}, contract_context=contrato_construtoras, document_identity={"periodo": "2T26"})
    resolucao = analyses["tables/t.json"].papeis["papel_periodo"]
    assert resolucao.papel_por_coluna == {}
    assert set(resolucao.ausentes) == set(PAPEIS)
    assert analyses["tables/t.json"].payload()["papeis_nao_resolvidos"] == {"papel_periodo": sorted(PAPEIS)}


def test_gabaritos_de_construtoras_concordam_com_a_derivacao_do_contrato(contrato_construtoras: dict[str, Any]) -> None:
    """Propriedade: em toda ancoragem cujo cabecalho e um periodo, ele e o periodo
    que o contrato deriva para o papel — a gramatica nao contradiz nenhum gabarito."""
    conferidas = 0
    for arquivo in GABARITOS.glob("*.json"):
        gabarito = json.loads(arquivo.read_text(encoding="utf-8"))
        if gabarito.get("dominio") != "construtoras":
            continue
        esperados = expected_periods_by_selector(contrato_construtoras, gabarito.get("identidade") or {})
        if not esperados:
            continue
        for anchors in (gabarito.get("ancoragens") or {}).values():
            for anchor in anchors:
                periodo_lido = parse_period_label(anchor.get("cabecalho_coluna"))
                if periodo_lido is None:
                    continue
                papel = anchor["seletores"]["papel_periodo"]
                assert periodo_lido == esperados["papel_periodo"][papel], (arquivo.name, anchor)
                conferidas += 1
    assert conferidas >= 20
