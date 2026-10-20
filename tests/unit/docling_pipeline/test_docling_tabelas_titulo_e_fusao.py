"""Tabelas do docling_pipeline: título certo por tabela e sem fusão de tabelas empilhadas.

Os dados reproduzem a página 8 do relatório da ABECIP (jun/2026): três tabelas empilhadas, cada uma
logo abaixo do seu título ("4 - Construcao", "5 - Aquisicao", "6 - Aquisicao e Construcao") e abaixo
do título largo da página. Geometria e cabeçalhos são os reais da extração.

Precisa de pandas; sem ele o módulo é ignorado (o CI de unidade só instala o núcleo).
"""

from __future__ import annotations

import pytest

pytest.importorskip("pandas")

import pandas as pd  # noqa: E402
from docling_pipeline.extractors import common, tables  # noqa: E402
from docling_pipeline.helpers import slugify  # noqa: E402
from docling_pipeline.models import BoundingBox, SectionRecord  # noqa: E402

PAGINA = 8
ESQUERDA, DIREITA = 116.7, 467.1

CABECALHO_AGENTES = [
    "Agentes",
    "Posicao: JUN/2026.R$ Milhoes",
    "Posicao: JUN/2026.Unidades",
    "Posicao: ano 2026.R$ Milhoes",
    "Posicao: ano 2026.Unidades",
]
CABECALHO_ANUAL = ["Anos.", "UnidadesFinanciadas.N°", "% no Ano", "Em Milhoes.R$", "Em Milhoes.% no Ano"]


def _secao(ordem: int, titulo: str, esquerda: float, direita: float, topo: float, base: float, pagina: int = PAGINA):
    return SectionRecord(
        section_id=f"secao-{pagina}-{ordem}",
        document_id="doc",
        page_number=pagina,
        title_raw=titulo,
        title_canonical=slugify(titulo),
        level_hint=1,
        order_index=ordem,
        bbox=BoundingBox(page_number=pagina, left=esquerda, right=direita, top=topo, bottom=base, coord_origin="BOTTOMLEFT"),
    )


def _secoes_pagina_8() -> list[SectionRecord]:
    return [
        _secao(95, "Indicadores do Crédito Imobiliário SBPE", 101.8, 514.8, 746.4, 728.0),
        _secao(96, "4 - Construcao", 119.0, 187.0, 712.2, 702.2),
        _secao(98, "5 - Aquisicao", 119.3, 179.3, 523.2, 511.9),
        _secao(100, "6 - Aquisicao e Construcao", 119.7, 242.0, 322.9, 311.6),
    ]


def _ancora(topo: float, pagina: int = PAGINA) -> BoundingBox:
    return BoundingBox(
        page_number=pagina, left=ESQUERDA, right=DIREITA, top=topo, bottom=topo - 160.0, coord_origin="BOTTOMLEFT"
    )


# Cada tabela começa logo abaixo do próprio título (mesmo desvio de ~0,6 pt observado na extração).
TOPOS = {97: 702.85, 99: 512.52, 101: 312.19}


def _candidato(
    indice: int,
    pagina: int,
    df: pd.DataFrame,
    secoes: list[SectionRecord],
    *,
    topo: float | None = None,
    closest_above: bool = True,
):
    anchor = _ancora(topo if topo is not None else TOPOS.get(indice, 600.0), pagina)
    secao = common.nearest_section(
        secoes, page_number=pagina, anchor_bbox=anchor, order_index=indice, closest_above=closest_above
    )
    titulo = secao.title_raw if secao else None
    return tables.ExtractedTableCandidate(
        source_order_indices=(indice,),
        page_number=pagina,
        end_page_number=pagina,
        section=secao,
        bbox=anchor,
        df=df,
        title_raw=titulo,
        title_canonical=slugify(titulo) if titulo else None,
    )


def _tabela_agentes(cabecalho: list[str], linhas: int) -> pd.DataFrame:
    corpo = [[f"BANCO {i}", "1,0", "2", "3,0", "4"] for i in range(linhas - 1)] + [["TOTAL", "9,0", "9", "9,0", "9"]]
    return pd.DataFrame(corpo, columns=cabecalho)


def _tres_tabelas(secoes: list[SectionRecord], cabecalhos: list[list[str]]):
    return [
        _candidato(97, PAGINA, _tabela_agentes(cabecalhos[0], 10), secoes),
        _candidato(99, PAGINA, _tabela_agentes(cabecalhos[1], 11), secoes),
        _candidato(101, PAGINA, _tabela_agentes(cabecalhos[2], 12), secoes),
    ]


def _processar(candidatos, secoes):
    return tables._merge_table_fragments(tables._propagate_headers(candidatos), secoes)


# --- A: título mais próximo acima da tabela -----------------------------------------------------


def test_closest_above_liga_a_tabela_ao_subtitulo_colado_nela():
    secoes = _secoes_pagina_8()
    for indice, esperado in ((97, "4 - Construcao"), (99, "5 - Aquisicao"), (101, "6 - Aquisicao e Construcao")):
        secao = common.nearest_section(
            secoes, page_number=PAGINA, anchor_bbox=_ancora(TOPOS[indice]), order_index=indice, closest_above=True
        )
        assert secao is not None and secao.title_raw == esperado


def test_regra_padrao_continua_preferindo_o_titulo_mais_largo():
    # Blocos, métricas e gráficos usam a regra padrão; ela não pode mudar com esta correção.
    secao = common.nearest_section(
        _secoes_pagina_8(), page_number=PAGINA, anchor_bbox=_ancora(TOPOS[97]), order_index=97
    )
    assert secao is not None and secao.title_raw == "Indicadores do Crédito Imobiliário SBPE"


def test_sem_titulo_acima_usa_a_regra_padrao():
    # Tabela no topo da página: todos os títulos estão abaixo dela e o mais próximo pertence ao bloco seguinte.
    secoes = [
        _secao(72, "Investimentos", 42.6, 110.2, 481.9, 470.8),
        _secao(76, "Capital Circulante Líquido", 42.6, 159.5, 177.5, 166.5),
    ]
    anchor = BoundingBox(page_number=PAGINA, left=41.1, right=553.3, top=738.7, bottom=496.6, coord_origin="BOTTOMLEFT")
    padrao = common.nearest_section(secoes, page_number=PAGINA, anchor_bbox=anchor, order_index=71)
    com_flag = common.nearest_section(secoes, page_number=PAGINA, anchor_bbox=anchor, order_index=71, closest_above=True)
    assert padrao is not None and com_flag is not None
    assert com_flag.title_raw == padrao.title_raw == "Capital Circulante Líquido"


# --- B2/B3: tabelas empilhadas não se fundem e cada uma mantém o próprio cabeçalho ----------------


def test_tres_tabelas_empilhadas_mantem_titulo_cabecalho_e_linhas():
    secoes = _secoes_pagina_8()
    anual = _candidato(89, 7, pd.DataFrame([["2010", "1", "2", "3", "4"]], columns=CABECALHO_ANUAL), [])
    resultado = _processar([anual, *_tres_tabelas(secoes, [CABECALHO_AGENTES] * 3)], secoes)

    abaixo = [c for c in resultado if c.page_number == PAGINA]
    assert [c.title_raw for c in abaixo] == ["4 - Construcao", "5 - Aquisicao", "6 - Aquisicao e Construcao"]
    assert [len(c.df) for c in abaixo] == [10, 11, 12]
    assert all(list(c.df.columns) == CABECALHO_AGENTES for c in abaixo)


def test_cabecalho_com_ano_nao_e_trocado_pelo_de_outra_tabela_de_mesma_largura():
    # "Posicao: JUN/2026..." parece dado (tem um ano) e a tabela anual vinha antes com 5 colunas.
    secoes = _secoes_pagina_8()
    anual = _candidato(89, 7, pd.DataFrame([["2010", "1", "2", "3", "4"]], columns=CABECALHO_ANUAL), [])
    [agentes] = [c for c in tables._propagate_headers([anual, _tres_tabelas(secoes, [CABECALHO_AGENTES] * 3)[0]])
                 if c.page_number == PAGINA]
    assert list(agentes.df.columns) == CABECALHO_AGENTES
    assert agentes.df.iloc[0, 0] == "BANCO 0"  # a primeira linha de dados não foi empurrada


def test_cabecalho_ainda_e_propagado_dentro_da_mesma_secao_e_largura():
    secoes = [_secao(10, "Resultado", 50.0, 500.0, 700.0, 690.0, pagina=1)]
    cabecalho = ["Conta", "2T26", "1T26", "Var"]
    primeira = _candidato(11, 1, pd.DataFrame([["Receita", "1", "2", "3"]], columns=cabecalho), secoes)
    continuacao = _candidato(12, 1, pd.DataFrame([["Custo", "4", "5", "6"]], columns=["column_1", "column_2", "column_3", "column_4"]), secoes)
    resultado = tables._propagate_headers([primeira, continuacao])
    assert list(resultado[1].df.columns) == cabecalho


def test_tabelas_de_secoes_diferentes_nao_trocam_cabecalho_so_pela_largura():
    secoes = [
        _secao(10, "Resultado", 50.0, 500.0, 700.0, 690.0, pagina=1),
        _secao(20, "Ratings", 50.0, 500.0, 400.0, 390.0, pagina=1),
    ]
    resultado_df = pd.DataFrame([["Receita", "1", "2", "3"]], columns=["Conta", "2T26", "1T26", "Var"])
    ratings = ["column_1", "column_2", "column_3", "column_4"]
    a = _candidato(11, 1, resultado_df, secoes, topo=685.0)  # logo abaixo de "Resultado"
    b = _candidato(21, 1, pd.DataFrame([["Fitch", "AAA", "AA", "Estavel"]], columns=ratings), secoes, topo=385.0)  # abaixo de "Ratings"
    resultado = tables._propagate_headers([a, b])
    assert [str(c) for c in resultado[1].df.columns] == ratings


# --- B2: continuação entre páginas continua sendo fundida ----------------------------------------


def _fragmento_com_cabecalho_e_corpo(pagina_corpo: int, secoes: list[SectionRecord]):
    esquerda = _candidato(30, 1, pd.DataFrame([], columns=["Conta", "2T26", "1T26", "Var"]), secoes)
    direita = _candidato(40, pagina_corpo, pd.DataFrame([["Receita", "1.234", "8.910", "12"]], columns=["1.234", "567", "8.910", "12"]), secoes)
    return esquerda, direita


def test_continuacao_na_pagina_seguinte_ainda_funde_mesmo_com_titulo_no_meio():
    secoes = [_secao(35, "P Á G I N A 2", 89.1, 150.8, 766.7, 759.1, pagina=2)]
    esquerda, direita = _fragmento_com_cabecalho_e_corpo(2, secoes)
    fundida = tables._merge_table_fragments([esquerda, direita], secoes)
    assert len(fundida) == 1 and list(fundida[0].df.columns) == ["Conta", "2T26", "1T26", "Var"]


def test_titulo_entre_fragmentos_da_mesma_pagina_impede_a_fusao():
    secoes = [_secao(35, "Outro bloco", 89.1, 400.0, 500.0, 490.0, pagina=1)]
    esquerda, direita = _fragmento_com_cabecalho_e_corpo(1, secoes)
    assert len(tables._merge_table_fragments([esquerda, direita], secoes)) == 2
    # sem o título no meio, é o mesmo caso de "cabeçalho num fragmento e corpo no outro": funde
    assert len(tables._merge_table_fragments([esquerda, direita], [])) == 1
