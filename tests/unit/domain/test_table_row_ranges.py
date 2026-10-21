"""Faixas de linhas de dados decididas por codigo para mapeamentos de tabela inteira."""

from __future__ import annotations

from typing import Any

import pytest

from document_processing.domain.fallback.table_row_ranges import (
    data_row_ranges,
    explicit_row_range_problems,
    fill_table_row_ranges,
    is_aggregate_label,
)


def _tabela(schema: list[str], rows: list[list[str]]) -> dict[str, Any]:
    return {"schema": schema, "rows": rows}


# Tabelas reais da ABECIP (Docling): cabecalho legivel no schema, TOTAL na ultima linha.
CONSTRUCAO_2026_01 = _tabela(
    ["Agentes", "Posicao: JAN 2026.Volume", "Posicao: JAN 2026.Unidades"],
    [
        ["CAIXA", "1.909,0", "9.180"],
        ["BRADESCO", "513,6", "1.741"],
        ["BRB", "146,2", "175"],
        ["ITAU UNIBANCO", "45.1", "244"],
        ["POUPEX", "0,7", "20"],
        ["BANRISUL", "0,3", "1"],
        ["TOTAL", "2.614,9", "11.361"],
    ],
)
MENSAL_2025_11 = _tabela(
    ["Meses.", "2024.Saldo", "2024.Variacao"],
    [[mes, "734.718", "-12.363"] for mes in ("Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "m", "Ago", "Set", "Out", "Nov", "Dez")],
)


@pytest.mark.parametrize(
    ("rotulo", "esperado"),
    [
        ("TOTAL", True),
        ("Total", True),
        ("Total Geral", True),
        ("  total  ", True),
        ("Sub-total", True),
        ("Subtotal", True),
        ("Sub total", True),
        ("Total de Unidades", True),
        ("Totalizador", False),
        ("Valor total das vendas", False),
        ("CAIXA", False),
        ("", False),
        (None, False),
    ],
)
def test_rotulo_de_agregacao_so_vale_no_comeco_do_rotulo(rotulo: object, esperado: bool) -> None:
    assert is_aggregate_label(rotulo) is esperado


def test_total_na_ultima_linha_fica_fora_da_faixa() -> None:
    assert data_row_ranges(CONSTRUCAO_2026_01) == ((0, 5),)


def test_primeira_linha_de_dados_entra_mesmo_sem_cabecalho_na_linha_zero() -> None:
    assert data_row_ranges(MENSAL_2025_11) == ((0, 11),)


def test_rotulo_ilegivel_de_ocr_continua_linha_de_dados() -> None:
    faixas = data_row_ranges(MENSAL_2025_11)
    assert faixas is not None
    assert faixas[0][0] <= 6 <= faixas[0][1]


def test_cabecalho_promovido_da_linha_zero_fica_fora() -> None:
    tabela = _tabela(
        ["column_1", "column_2", "column_3"],
        [["Agentes", "Volume", "Unidades"], ["CAIXA", "1.909,0", "9.180"], ["BRB", "146,2", "175"], ["TOTAL", "2.055,2", "9.355"]],
    )
    assert data_row_ranges(tabela) == ((1, 2),)


def test_titulo_de_segmento_divide_a_tabela_em_duas_faixas() -> None:
    tabela = _tabela(
        ["Item", "2025", "2024"],
        [
            ["Construcao", "", ""],
            ["CAIXA", "10", "9"],
            ["BRB", "2", "1"],
            ["Aquisicao", "", ""],
            ["CAIXA", "20", "19"],
            ["BRB", "4", "3"],
        ],
    )
    assert data_row_ranges(tabela) == ((1, 2), (4, 5))


def test_subtotal_no_meio_fecha_a_faixa_e_a_proxima_recomeca() -> None:
    tabela = _tabela(
        ["Item", "Valor", "Qtd"],
        [["A", "1,0", "1"], ["B", "2,0", "2"], ["Subtotal", "3,0", "3"], ["C", "4,0", "4"], ["Total", "7,0", "7"]],
    )
    assert data_row_ranges(tabela) == ((0, 1), (3, 3))


def test_nota_sem_valor_no_comeco_ou_no_fim_nao_entra() -> None:
    tabela = _tabela(
        ["Item", "Valor", "Qtd"],
        [["Posicao em maio", "", ""], ["A", "1,0", "1"], ["B", "2,0", "2"], ["Fonte: ABECIP", "", ""]],
    )
    assert data_row_ranges(tabela) == ((1, 2),)


def test_linha_sem_valor_numerico_entre_duas_linhas_de_dados_fica_dentro_da_faixa() -> None:
    tabela = _tabela(
        ["Agentes", "Volume", "Unidades"],
        [["CAIXA", "9,0", "9"], ["SAFRA", "n/d", "n/d"], ["BRB", "1,0", "1"], ["TOTAL", "10,0", "10"]],
    )
    assert data_row_ranges(tabela) == ((0, 2),)


def test_linha_so_com_rotulo_e_titulo_de_segmento_como_na_estrutura_da_tabela() -> None:
    """Mesma definicao de ``read_table_structure``: rotulo sem nenhuma outra celula abre um segmento."""
    tabela = _tabela(
        ["Agentes", "Volume", "Unidades"],
        [["CAIXA", "9,0", "9"], ["SAFRA", "", ""], ["BRB", "1,0", "1"]],
    )
    assert data_row_ranges(tabela) == ((0, 0), (2, 2))


def test_celula_de_traco_conta_como_valor() -> None:
    tabela = _tabela(["Agentes", "Volume", "Unidades"], [["CAIXA", "9,0", "9"], ["SAFRA", "-", "-"], ["TOTAL", "9,0", "9"]])
    assert data_row_ranges(tabela) == ((0, 1),)


def test_tabela_sem_linha_de_dados_devolve_vazio() -> None:
    assert data_row_ranges(_tabela(["Agentes", "Volume", "Unidades"], [["TOTAL", "0", "0"]])) == ()
    assert data_row_ranges(_tabela(["Agentes", "Volume", "Unidades"], [])) == ()


def test_artefato_que_nao_e_tabela_devolve_none() -> None:
    assert data_row_ranges({"kind": "chart", "series": []}) is None
    assert data_row_ranges({"object_key": "x", "sample": {"nada": 1}}) is None


def test_envelope_do_carregamento_para_a_llm_tambem_vale() -> None:
    assert data_row_ranges({"object_key": "tables/t.json", "formato": "json", "sample": CONSTRUCAO_2026_01}) == ((0, 5),)


def test_faixa_nunca_passa_do_fim_da_tabela() -> None:
    for tabela in (CONSTRUCAO_2026_01, MENSAL_2025_11):
        faixas = data_row_ranges(tabela)
        assert faixas is not None
        assert all(0 <= inicio <= fim < len(tabela["rows"]) for inicio, fim in faixas)


# Mensal com o ano anterior completo (colunas 1-2) e o corrente so ate junho (colunas 3-4).
MENSAL_ANO_CORRENTE_ATE_JUNHO = _tabela(
    ["Meses", "2025.Unidades", "2025.Volume", "2026.Unidades", "2026.Volume"],
    [
        [mes, "30.000", "10.000", "35.000" if i < 6 else "", "12.000" if i < 6 else ""]
        for i, mes in enumerate(("Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"))
    ],
)


def test_sem_colunas_qualquer_valor_da_linha_conta_e_os_meses_futuros_entram() -> None:
    assert data_row_ranges(MENSAL_ANO_CORRENTE_ATE_JUNHO) == ((0, 11),)


def test_com_as_colunas_lidas_so_conta_a_linha_com_valor_nelas() -> None:
    assert data_row_ranges(MENSAL_ANO_CORRENTE_ATE_JUNHO, colunas=[3, 4]) == ((0, 5),)
    assert data_row_ranges(MENSAL_ANO_CORRENTE_ATE_JUNHO, colunas=[1, 2]) == ((0, 11),)
    assert data_row_ranges(MENSAL_ANO_CORRENTE_ATE_JUNHO, colunas=[3]) == ((0, 5),)


def test_coluna_fora_da_tabela_nao_quebra_e_nao_cria_faixa() -> None:
    assert data_row_ranges(MENSAL_ANO_CORRENTE_ATE_JUNHO, colunas=[99]) == ()


# --- preencher as faixas de um mapeamento -----------------------------------

CAMPOS_VOLUME_E_UNIDADES = [
    {"caminho_saida": "instituicao", "indice_coluna": 0},
    {"caminho_saida": "volume", "indice_coluna": 1, "tipo": "numero"},
    {"caminho_saida": "unidades", "indice_coluna": 2, "tipo": "numero"},
]


def _linhas_de_tabela(**extra: Any) -> dict[str, Any]:
    return {"tipo_origem": "linhas_de_tabela", "arquivo_origem": "tables/t1.json", "campos": CAMPOS_VOLUME_E_UNIDADES, **extra}


def test_instrucao_sem_faixa_le_a_tabela_inteira_pelo_codigo() -> None:
    mapeamento = {"colecao": _linhas_de_tabela()}
    preenchido = fill_table_row_ranges(mapeamento, {"tables/t1.json": CONSTRUCAO_2026_01})
    assert (preenchido.mapeamento["colecao"]["linha_inicial"], preenchido.mapeamento["colecao"]["linha_final"]) == (0, 5)
    assert preenchido.registro == [{"caminho": "colecao", "arquivo_origem": "tables/t1.json", "acao": "faixa_do_codigo", "faixas": [[0, 5]]}]


def test_o_mapeamento_recebido_nao_e_alterado() -> None:
    mapeamento = {"colecao": _linhas_de_tabela()}
    fill_table_row_ranges(mapeamento, {"tables/t1.json": CONSTRUCAO_2026_01})
    assert "linha_inicial" not in mapeamento["colecao"]


def test_so_as_colunas_numericas_lidas_decidem_a_faixa() -> None:
    campos_do_ano_corrente = [
        {"caminho_saida": "mes", "indice_coluna": 0},
        {"caminho_saida": "unidades", "indice_coluna": 3, "tipo": "numero"},
    ]
    mapeamento = {"serie": _linhas_de_tabela(campos=campos_do_ano_corrente)}
    preenchido = fill_table_row_ranges(mapeamento, {"tables/t1.json": MENSAL_ANO_CORRENTE_ATE_JUNHO})
    assert preenchido.mapeamento["serie"]["linha_final"] == 5


def test_faixa_explicita_da_llm_nao_e_tocada() -> None:
    for faixa in ({"linha_inicial": 1, "linha_final": 3}, {"segmentos": [{"linha_inicial": 0, "linha_final": 2}]}, {"faixas_linhas": [{"linha_inicial": 0, "linha_final": 2}]}):
        mapeamento = {"colecao": _linhas_de_tabela(**faixa)}
        preenchido = fill_table_row_ranges(mapeamento, {"tables/t1.json": CONSTRUCAO_2026_01})
        assert preenchido.mapeamento == mapeamento
        assert [item["acao"] for item in preenchido.registro] == ["faixa_da_llm"]


def test_cada_fonte_de_linhas_de_tabelas_e_decidida_separadamente() -> None:
    mapeamento = {
        "colecao": {
            "tipo_origem": "linhas_de_tabelas",
            "fontes": [
                {"arquivo_origem": "tables/a.json", "campos": CAMPOS_VOLUME_E_UNIDADES, "valores_por_segmento": {"modalidade": "construcao"}},
                {"arquivo_origem": "tables/b.json", "campos": CAMPOS_VOLUME_E_UNIDADES, "linha_inicial": 0, "linha_final": 3},
                {"arquivo_origem": "tables/c.json", "campos": CAMPOS_VOLUME_E_UNIDADES},
            ],
        }
    }
    tabelas = {"tables/a.json": CONSTRUCAO_2026_01, "tables/b.json": CONSTRUCAO_2026_01}
    preenchido = fill_table_row_ranges(mapeamento, tabelas)
    fontes = preenchido.mapeamento["colecao"]["fontes"]
    assert (fontes[0]["linha_inicial"], fontes[0]["linha_final"]) == (0, 5)
    assert fontes[0]["valores_por_segmento"] == {"modalidade": "construcao"}
    assert (fontes[1]["linha_inicial"], fontes[1]["linha_final"]) == (0, 3)
    assert "linha_inicial" not in fontes[2]
    assert [item["acao"] for item in preenchido.registro] == ["faixa_do_codigo", "faixa_da_llm", "tabela_nao_carregada"]


def test_varias_faixas_viram_segmentos_que_levam_os_valores_da_fonte() -> None:
    tabela = _tabela(
        ["Item", "Valor", "Qtd"],
        [["A", "1,0", "1"], ["B", "2,0", "2"], ["Subtotal", "3,0", "3"], ["C", "4,0", "4"], ["Total", "7,0", "7"]],
    )
    mapeamento = {"colecao": _linhas_de_tabela(valores_por_segmento={"modalidade": "construcao"})}
    instrucao = fill_table_row_ranges(mapeamento, {"tables/t1.json": tabela}).mapeamento["colecao"]
    assert instrucao["segmentos"] == [
        {"linha_inicial": 0, "linha_final": 1, "valores_por_segmento": {"modalidade": "construcao"}},
        {"linha_inicial": 3, "linha_final": 3, "valores_por_segmento": {"modalidade": "construcao"}},
    ]
    assert "linha_inicial" not in instrucao


def test_tabela_sem_linhas_de_dados_e_o_que_nao_e_linhas_de_tabela_ficam_como_vieram() -> None:
    celula = {"tipo_origem": "celula_de_tabela", "arquivo_origem": "tables/t1.json", "seletor_linha": {"valor_aceito": "X"}}
    mapeamento = {"vazia": _linhas_de_tabela(arquivo_origem="tables/vazia.json"), "celula": celula}
    tabelas = {"tables/t1.json": CONSTRUCAO_2026_01, "tables/vazia.json": _tabela(["a", "b", "c"], [["TOTAL", "1", "2"]])}
    preenchido = fill_table_row_ranges(mapeamento, tabelas)
    assert preenchido.mapeamento == mapeamento
    assert [item["acao"] for item in preenchido.registro] == ["sem_linhas_de_dados"]


def test_artefato_no_formato_do_carregamento_para_a_llm_tambem_serve() -> None:
    envelope = {"object_key": "tables/t1.json", "formato": "json", "sample": CONSTRUCAO_2026_01}
    preenchido = fill_table_row_ranges({"colecao": _linhas_de_tabela()}, {"tables/t1.json": envelope})
    assert preenchido.mapeamento["colecao"]["linha_final"] == 5


# --- faixa explicita que o resolvedor descartaria em silencio ---------------


def test_linha_final_alem_da_ultima_linha_e_apontada_com_o_tamanho_da_tabela() -> None:
    mapeamento = {"colecao": _linhas_de_tabela(linha_inicial=1, linha_final=7)}
    problemas = explicit_row_range_problems(mapeamento, {"tables/t1.json": CONSTRUCAO_2026_01})
    assert len(problemas) == 1
    assert "linha_final 7" in problemas[0] and "7 linhas" in problemas[0] and "0 a 6" in problemas[0]


def test_faixa_que_cabe_na_tabela_nao_gera_problema_em_nenhuma_forma() -> None:
    tabelas = {"tables/t1.json": CONSTRUCAO_2026_01}
    formas = (
        {"linha_inicial": 0, "linha_final": 6},
        {"segmentos": [{"linha_inicial": 0, "linha_final": 6}]},
        {"faixas_linhas": [[0, 3], [4, 6]]},
        {"linha_inicial": 2},
    )
    for faixa in formas:
        assert explicit_row_range_problems({"colecao": _linhas_de_tabela(**faixa)}, tabelas) == []


def test_faixas_invalidas_sao_apontadas_em_segmentos_e_em_fontes() -> None:
    mapeamento = {
        "a": _linhas_de_tabela(segmentos=[{"linha_inicial": 0, "linha_final": 2}, {"linha_inicial": 4, "linha_final": 3}]),
        "b": {"tipo_origem": "linhas_de_tabelas", "fontes": [{"arquivo_origem": "tables/t1.json", "campos": [], "linha_inicial": -1, "linha_final": 2}]},
    }
    problemas = explicit_row_range_problems(mapeamento, {"tables/t1.json": CONSTRUCAO_2026_01})
    assert len(problemas) == 2
    assert problemas[0].startswith("a ") and problemas[1].startswith("b ")


def test_tabela_nao_carregada_ou_sem_faixa_explicita_nao_e_verificada() -> None:
    assert explicit_row_range_problems({"colecao": _linhas_de_tabela(linha_final=99)}, {}) == []
    assert explicit_row_range_problems({"colecao": _linhas_de_tabela()}, {"tables/t1.json": CONSTRUCAO_2026_01}) == []
