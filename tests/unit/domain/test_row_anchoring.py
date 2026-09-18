"""Fase 3.2: ancoragem de linha por sinonimo do contrato."""

from __future__ import annotations

from document_processing.domain.fallback.row_anchoring import (
    ResolvedRowAnchor,
    indicator_synonyms_for_entry,
    resolve_row_anchor,
)

METRICAS_CONSTRUTORAS = {
    "vendas": {
        "indicadores": {
            "numero_de_unidades": {
                "sinonimos": [
                    "Número de Unidades",
                    "unidades vendidas",
                    "vendas contratadas brutas",
                ]
            }
        }
    },
    "lancamentos": {
        "indicadores": {
            "numero_de_unidades": {"sinonimos": ["Número de Unidades", "unidades lançadas"]}
        }
    },
}

METRICAS_BANCOS = {
    "grupo_unico": {
        "indicadores": {
            "resultado_recorrente": {"sinonimos": ["Resultado recorrente", "Lucro líquido recorrente"]},
            "margem_financeira": {"sinonimos": ["Margem financeira"]},
        }
    }
}

TABELA_VENDAS = {
    "rows": [
        ["Vendas Contratadas Brutas (Unidades)", "3601", "3536", "3570"],
        ["Vendas Líquidas 100% (Unid.)", "3351", "3105", "3136"],
    ]
}


def test_indicador_unico_no_grupo_resolve_por_segmento_do_path():
    sinonimos = indicator_synonyms_for_entry(
        requisito="balancos_das_empresas.vendas.dados.valores.valor",
        seletores={"papel_periodo": "periodo_referencia"},
        metric_groups=METRICAS_CONSTRUTORAS,
    )
    assert "vendas contratadas brutas" in sinonimos


def test_indicador_por_seletor_direto_bancos():
    sinonimos = indicator_synonyms_for_entry(
        requisito="indicadores_monetarios.dados.valores.valor",
        seletores={"indicador": "resultado_recorrente", "papel_periodo": "periodo_referencia"},
        metric_groups=METRICAS_BANCOS,
    )
    assert "resultado recorrente" in {s.lower() for s in sinonimos}
    assert "margem financeira" not in {s.lower() for s in sinonimos}


def test_sem_seletor_e_grupo_ambiguo_nao_resolve():
    metricas_ambiguas = {
        "grupo": {
            "indicadores": {
                "a": {"sinonimos": ["A"]},
                "b": {"sinonimos": ["B"]},
            }
        }
    }
    sinonimos = indicator_synonyms_for_entry(
        requisito="raiz.grupo.dados.valores.valor",
        seletores={},
        metric_groups=metricas_ambiguas,
    )
    assert sinonimos == set()


def test_resolve_linha_unica_entre_rotulos_parecidos():
    sinonimos = indicator_synonyms_for_entry(
        requisito="balancos_das_empresas.vendas.dados.valores.valor",
        seletores={},
        metric_groups=METRICAS_CONSTRUTORAS,
    )
    ancora = resolve_row_anchor(synonyms=sinonimos, tables={"tables/table002.json": TABELA_VENDAS})
    assert ancora == ResolvedRowAnchor(
        arquivo_origem="tables/table002.json",
        rotulo_linha="Vendas Contratadas Brutas (Unidades)",
        indice_linha=0,
    )


def test_sinonimo_generico_que_casa_duas_linhas_fica_ambiguo():
    # "unidades vendidas" nao aparece literalmente em nenhum rotulo aqui, mas um
    # sinonimo generico demais (sem o "brutas"/"liquidas") casaria as duas linhas.
    ancora = resolve_row_anchor(
        synonyms={"vendas"},
        tables={"tables/table002.json": TABELA_VENDAS},
    )
    assert ancora is None


def test_sem_match_nenhuma_linha_fica_com_a_llm():
    ancora = resolve_row_anchor(
        synonyms={"margem financeira"},
        tables={"tables/table002.json": TABELA_VENDAS},
    )
    assert ancora is None


def test_mesma_linha_casa_duas_tabelas_diferentes_fica_ambiguo():
    ancora = resolve_row_anchor(
        synonyms={"vendas contratadas brutas"},
        tables={
            "tables/table002.json": TABELA_VENDAS,
            "tables/table009.json": TABELA_VENDAS,
        },
    )
    assert ancora is None


def test_grafico_sem_rows_e_ignorado():
    ancora = resolve_row_anchor(
        synonyms={"vendas contratadas brutas"},
        tables={"charts/chart001.json": {"series": []}},
    )
    assert ancora is None


def test_sinonimo_curto_demais_e_descartado():
    ancora = resolve_row_anchor(
        synonyms={"a", "ab"},
        tables={"tables/table002.json": TABELA_VENDAS},
    )
    assert ancora is None
