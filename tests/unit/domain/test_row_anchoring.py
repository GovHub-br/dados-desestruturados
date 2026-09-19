"""Fase 3.2: ancoragem de linha por sinonimo do contrato."""

from __future__ import annotations

from document_processing.domain.fallback.row_anchoring import (
    ResolvedRowAnchor,
    classify_table_metric_group,
    indicator_group_for_entry,
    indicator_synonyms_for_entry,
    resolve_row_anchor,
    table_metric_groups,
)

METRICAS_CONSTRUTORAS = {
    "vendas": {
        "tipo_operacao": "venda",
        "indicadores": {
            "numero_de_unidades": {
                "sinonimos": [
                    "Número de Unidades",
                    "unidades vendidas",
                    "vendas contratadas brutas",
                ]
            }
        },
    },
    "lancamentos": {
        "tipo_operacao": "lancamento",
        "indicadores": {
            "numero_de_unidades": {"sinonimos": ["Número de Unidades", "unidades lançadas"]}
        },
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


def test_linha_de_texto_corrido_que_cita_o_indicador_de_passagem_nao_conta():
    # Caso real (itau, exp-fase2-bugfix-desembrulho): uma tabela de "Guidance"
    # cita o nome do indicador num paragrafo, mas a celula ao lado e uma frase
    # ("Crescimento entre..."), nao um valor. Sem checagem de celula numerica,
    # isso virava o unico match e forcava uma ancora errada.
    tabela_guidance = {
        "rows": [
            ["Carteira de crédito total¹ Carteira de crédito - Brasil", "Crescimento entre 5,5% e 9,5%"],
        ]
    }
    ancora = resolve_row_anchor(
        synonyms={"carteira de credito"},
        tables={"tables/table006.json": tabela_guidance},
    )
    assert ancora is None


def test_ambiguidade_falsa_eliminada_quando_so_a_tabela_errada_bate_o_rotulo():
    # A tabela certa ("Total¹") nao contem o sinonimo no proprio rotulo; so a
    # tabela de guidance bate o texto. Antes da checagem numerica isso virava
    # um match unico (errado); agora nenhuma linha sobrevive e a decisao volta
    # pra LLM (residuo), em vez de uma ancora forcada e incorreta.
    tabela_carteira = {"rows": [["Total¹", "1.522,4"]]}
    tabela_guidance = {
        "rows": [
            ["Carteira de crédito total¹ Carteira de crédito - Brasil", "Crescimento entre 5,5% e 9,5%"],
        ]
    }
    ancora = resolve_row_anchor(
        synonyms={"carteira de credito"},
        tables={
            "tables/table002.json": tabela_carteira,
            "tables/table006.json": tabela_guidance,
        },
    )
    assert ancora is None


def test_celula_percentual_conta_como_valor_numerico():
    tabela = {"rows": [["Margem financeira", "12,3%"]]}
    ancora = resolve_row_anchor(synonyms={"margem financeira"}, tables={"tables/table002.json": tabela})
    assert ancora == ResolvedRowAnchor(
        arquivo_origem="tables/table002.json", rotulo_linha="Margem financeira", indice_linha=0
    )


def test_classifica_tabela_pelo_vocabulario_majoritario_dos_rotulos():
    grupos = table_metric_groups(
        {"tables/table003.json": TABELA_VENDAS},
        label_columns=None,
        metric_groups=METRICAS_CONSTRUTORAS,
    )
    assert grupos == {"tables/table003.json": "vendas"}


def test_sem_maioria_clara_tabela_fica_sem_grupo_classificado():
    tabela_ambigua = {"rows": [["Numero de Unidades", "100"]]}
    grupo = classify_table_metric_group(
        tabela_ambigua["rows"],
        0,
        {"vendas": {"numero de unidades"}, "lancamentos": {"numero de unidades"}},
    )
    assert grupo is None


def test_grupo_generico_compartilhado_nao_vaza_para_tabela_do_outro_grupo():
    # Caso real (eztc3, exp-fase2-ancoragem-numerica): so a tabela de vendas foi
    # carregada; "Numero de Unidades" e sinonimo generico tanto de vendas quanto
    # de lancamentos, e sem a classificacao por grupo essa tabela de vendas
    # tambem virava a ancora (errada) do indicador de lancamentos.
    sinonimos_lancamentos = indicator_synonyms_for_entry(
        requisito="balancos_das_empresas.lancamentos.dados.valores.valor",
        seletores={},
        metric_groups=METRICAS_CONSTRUTORAS,
    )
    grupo_tabela = table_metric_groups(
        {"tables/table003.json": TABELA_VENDAS},
        label_columns=None,
        metric_groups=METRICAS_CONSTRUTORAS,
    )
    ancora = resolve_row_anchor(
        synonyms=sinonimos_lancamentos,
        tables={"tables/table003.json": TABELA_VENDAS},
        table_groups=grupo_tabela,
        entry_group=indicator_group_for_entry(
            requisito="balancos_das_empresas.lancamentos.dados.valores.valor",
            seletores={},
            metric_groups=METRICAS_CONSTRUTORAS,
        ),
    )
    assert ancora is None


def test_vocabulario_de_linha_nao_decide_sozinho_sem_o_nome_da_tabela():
    # Reproduz o achado real (eztc3, exp-fase2-item24-escopo antes do fix do
    # nome): a tabela de vendas tem so UMA linha com vocabulario de indicador
    # ("Numero de unidades"), e esse sinonimo e compartilhado com lancamentos
    # — as demais linhas ("VSO", "Distratos", "Preco Medio") nao aparecem em
    # nenhum sinonimo do contrato. Contagem de linha sozinha empata 1 a 1 e
    # nao decide; so o titulo da tabela ("name") resolve.
    tabela_vendas_real = {
        "rows": [
            ["Vendas Brutas", "675,1"],
            ["Preço Médio", "815"],
            ["VSO Bruta (%)", "16,9%"],
            ["Distratos", "97,5"],
            ["Número de unidades (#)", "756"],
        ]
    }
    grupo_sem_nome = table_metric_groups(
        {"tables/table003.json": tabela_vendas_real},
        label_columns=None,
        metric_groups=METRICAS_CONSTRUTORAS,
    )
    assert grupo_sem_nome == {}

    tabela_vendas_com_nome = {**tabela_vendas_real, "name": "Vendas"}
    grupo_com_nome = table_metric_groups(
        {"tables/table003.json": tabela_vendas_com_nome},
        label_columns=None,
        metric_groups=METRICAS_CONSTRUTORAS,
    )
    assert grupo_com_nome == {"tables/table003.json": "vendas"}


def test_titulo_da_tabela_de_lancamentos_tambem_classifica():
    tabela_lancamentos = {"name": "Lançamentos", "rows": [["1T", "2.022"], ["2T", "914"]]}
    grupo = table_metric_groups(
        {"tables/table002.json": tabela_lancamentos},
        label_columns=None,
        metric_groups=METRICAS_CONSTRUTORAS,
    )
    assert grupo == {"tables/table002.json": "lancamentos"}


def test_nome_generico_de_tabela_nao_classifica_nada():
    tabela = {"name": "Table 3", "rows": [["Numero de Unidades", "100"]]}
    grupo = classify_table_metric_group(
        tabela["rows"],
        0,
        {"vendas": {"numero de unidades"}, "lancamentos": {"numero de unidades"}},
        nome_tabela=tabela["name"],
        group_title_terms={"vendas": {"vendas", "venda"}, "lancamentos": {"lancamentos", "lancamento"}},
    )
    assert grupo is None


def test_nome_da_tabela_impede_vazamento_mesmo_sem_linha_distintiva():
    # Versao completa do achado eztc3, com o `name` que o Docling sempre
    # preenche: a tabela de vendas (so com o sinonimo generico compartilhado)
    # deixa de contaminar o indicador de lancamentos.
    tabela_vendas_real = {
        "name": "Vendas",
        "rows": [
            ["Vendas Brutas", "675,1"],
            ["Preço Médio", "815"],
            ["VSO Bruta (%)", "16,9%"],
            ["Distratos", "97,5"],
            ["Número de unidades (#)", "756"],
        ],
    }
    sinonimos_lancamentos = indicator_synonyms_for_entry(
        requisito="balancos_das_empresas.lancamentos.dados.valores.valor",
        seletores={},
        metric_groups=METRICAS_CONSTRUTORAS,
    )
    grupo_tabela = table_metric_groups(
        {"tables/table003.json": tabela_vendas_real},
        label_columns=None,
        metric_groups=METRICAS_CONSTRUTORAS,
    )
    ancora = resolve_row_anchor(
        synonyms=sinonimos_lancamentos,
        tables={"tables/table003.json": tabela_vendas_real},
        table_groups=grupo_tabela,
        entry_group=indicator_group_for_entry(
            requisito="balancos_das_empresas.lancamentos.dados.valores.valor",
            seletores={},
            metric_groups=METRICAS_CONSTRUTORAS,
        ),
    )
    assert ancora is None


def test_grupo_certo_continua_resolvendo_normalmente():
    sinonimos_vendas = indicator_synonyms_for_entry(
        requisito="balancos_das_empresas.vendas.dados.valores.valor",
        seletores={},
        metric_groups=METRICAS_CONSTRUTORAS,
    )
    grupo_tabela = table_metric_groups(
        {"tables/table002.json": TABELA_VENDAS},
        label_columns=None,
        metric_groups=METRICAS_CONSTRUTORAS,
    )
    ancora = resolve_row_anchor(
        synonyms=sinonimos_vendas,
        tables={"tables/table002.json": TABELA_VENDAS},
        table_groups=grupo_tabela,
        entry_group=indicator_group_for_entry(
            requisito="balancos_das_empresas.vendas.dados.valores.valor",
            seletores={},
            metric_groups=METRICAS_CONSTRUTORAS,
        ),
    )
    assert ancora == ResolvedRowAnchor(
        arquivo_origem="tables/table002.json",
        rotulo_linha="Vendas Contratadas Brutas (Unidades)",
        indice_linha=0,
    )


def test_linha_da_marca_prevalece_sobre_categoria_consolidada():
    # Caso real (direcional, exp-fase2-ancoragem-numerica): a linha-categoria
    # "Unidades Lancadas" (consolidado = 5511) e seguida das linhas por marca
    # "Direcional" (3896) e "Riva" (1615). O gabarito quer o valor da marca do
    # proprio documento, nao o consolidado.
    tabela_direcional = {
        "rows": [
            ["Unidades Lancadas", "5511"],
            ["Direcional", "3896"],
            ["Riva", "1615"],
        ]
    }
    ancora = resolve_row_anchor(
        synonyms={"unidades lancadas"},
        tables={"tables/table001.json": tabela_direcional},
        document_entity="direcional",
    )
    assert ancora == ResolvedRowAnchor(
        arquivo_origem="tables/table001.json", rotulo_linha="Direcional", indice_linha=1
    )


def test_sem_entidade_do_documento_mantem_a_linha_consolidada():
    tabela_direcional = {
        "rows": [
            ["Unidades Lancadas", "5511"],
            ["Direcional", "3896"],
            ["Riva", "1615"],
        ]
    }
    ancora = resolve_row_anchor(
        synonyms={"unidades lancadas"},
        tables={"tables/table001.json": tabela_direcional},
    )
    assert ancora == ResolvedRowAnchor(
        arquivo_origem="tables/table001.json", rotulo_linha="Unidades Lancadas", indice_linha=0
    )


def test_duas_marcas_batendo_a_mesma_entidade_no_bloco_fica_ambiguo():
    tabela = {
        "rows": [
            ["Unidades Lancadas", "5511"],
            ["Direcional Engenharia", "2000"],
            ["Direcional Riva", "1896"],
        ]
    }
    ancora = resolve_row_anchor(
        synonyms={"unidades lancadas"},
        tables={"tables/table001.json": tabela},
        document_entity="direcional",
    )
    assert ancora is None
