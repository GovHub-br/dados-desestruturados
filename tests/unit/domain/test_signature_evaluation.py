"""Metricas por fase da assinatura de layout, definidas sobre contrato e gabarito."""

from __future__ import annotations

from document_processing.domain.observability.signature_evaluation import (
    anchoring_metrics,
    column_role_metrics,
    expected_entries_metrics,
    resolved_observation_metrics,
    selection_metrics,
    structural_metrics,
)

CONTRATO = {
    "schema_saida": {
        "g": {"dados": [{"empresa": "string", "valores": [{"periodo": "string", "escopo_periodo": "trimestre", "valor": "number | null"}]}]},
    },
    "contrato_semantico": {
        "chaves_de_item": {
            "g.dados": {"chave": "empresa", "origem_valor": "identidade_documento"},
            "g.dados.valores": {"chave": "papel", "origem_valor": "seletor_observacao"},
        },
        "requisitos_mapeamento": {
            "campos_obrigatorios": [
                {
                    "path": "g.dados.valores.valor",
                    "observacoes_obrigatorias": [
                        {"seletores": {"papel": "ref"}, "campos_contexto_obrigatorios": ["periodo"]},
                        {"seletores": {"papel": "ant"}, "campos_contexto_obrigatorios": ["periodo"], "obrigatorio": False},
                    ],
                }
            ]
        },
    },
}


def _entrada(arquivo="tables/t1.json", rotulo="Unidades", indice=None, coluna=1):
    linha = {"coluna_rotulo": 0, "valor_aceito": rotulo}
    if indice is not None:
        linha["indice_linha_esperado"] = indice
    return {"tipo_origem": "celula_de_tabela", "arquivo_origem": arquivo, "seletor_linha": linha, "seletor_coluna": {"indice_coluna_esperado": coluna}}


def _m(metrics):
    return {m.name: m.value for m in metrics}


def test_estrutura_boa_zera_erros_e_cobre_observacoes() -> None:
    mapping = {
        "g.dados[empresa=Acme].valores[papel=ref].valor": _entrada(),
        "g.dados[empresa=Acme].valores[papel=ref].periodo": _entrada(),
        "g.dados[empresa=Acme].valores[papel=ant].valor": _entrada(coluna=2),
    }
    m = _m(structural_metrics(mapping, CONTRATO))
    assert m["assinatura_f1_array_sem_filtro"] == 0
    assert m["assinatura_f1_filtro_chave_declarada"] == 1.0
    assert m["assinatura_f1_filtro_seletor_igual_ao_contrato"] == 1.0
    assert m["assinatura_f1_entidades_no_candidato"] == 1
    assert m["assinatura_f1_cobertura_obrigatorios"] == 1.0
    assert m["assinatura_f1_cobertura_opcionais"] == 1.0
    assert m["assinatura_f1_estrutura_valida"] is True


def test_literal_no_lugar_do_papel_e_array_sem_filtro_sao_contados() -> None:
    mapping = {
        "g.dados.valores[papel=ref].valor": _entrada(),  # atravessa g.dados sem filtro
        "g.dados[empresa=Acme].valores[periodo=1T26].valor": _entrada(),  # chave errada + literal
        "g.dados[empresa=Outra].valores[papel=ant].valor": _entrada(),
    }
    m = _m(structural_metrics(mapping, CONTRATO))
    assert m["assinatura_f1_array_sem_filtro"] == 1
    assert m["assinatura_f1_filtro_chave_declarada"] < 1.0
    assert m["assinatura_f1_filtro_papel_literal"] == 1  # 1T26 onde o contrato pede um papel
    assert m["assinatura_f1_entidades_no_candidato"] == 2
    assert m["assinatura_f1_estrutura_valida"] is False


def test_selecao_precisao_e_revocacao_contra_o_gabarito() -> None:
    gabarito = {"artefatos_esperados_por_requisito": {"g.dados.valores.valor": ["tables/t1.json"]}}
    selecao = {
        "artifact_paths": [
            {"path": "tables/t1.json", "coberturas": [{"campo_saida": "g.dados.valores.valor", "ancoras": ["x"]}]},
            {"path": "tables/t9.json", "coberturas": [{"campo_saida": "g.dados.valores.valor", "ancoras": ["y"]}]},
        ]
    }
    m = _m(selection_metrics(selecao, gabarito))
    assert m["assinatura_f0_selecao_precisao"] == 0.5
    assert m["assinatura_f0_selecao_revocacao"] == 1.0
    assert m["assinatura_f0_selecao_artefatos_por_requisito"] == 2.0


def test_ancoragem_exige_rotulo_e_indice_quando_informado() -> None:
    gabarito = {
        "ancoragens": {
            "g.dados.valores.valor": [
                {"seletores": {"empresa": "acme", "papel": "ref"}, "arquivo_origem": "tables/t1.json", "indice_linha": 5, "rotulo_linha": "Unidades", "indice_coluna": 1},
                {"seletores": {"empresa": "acme", "papel": "ant"}, "arquivo_origem": "tables/t1.json", "indice_linha": 5, "rotulo_linha": "Unidades", "indice_coluna": 2},
            ]
        },
        "ausencias_esperadas": [{"requisito": "g.dados.valores.valor", "seletores": {"papel": "outro"}}],
    }
    mapping = {
        "g.dados[empresa=Acme].valores[papel=ref].valor": _entrada(indice=5),
        "g.dados[empresa=Acme].valores[papel=ant].valor": _entrada(indice=8, coluna=3),  # linha errada, coluna errada
        "g.dados[empresa=Acme].valores[papel=outro].valor": _entrada(),  # gabarito diz ausente
    }
    m = _m(anchoring_metrics(mapping, gabarito, unmapped=[]))
    assert m["assinatura_f3_arquivo_origem_correto"] == 1.0
    assert m["assinatura_f3_rotulo_linha_correto"] == 0.5
    assert m["assinatura_f3_indice_coluna_correto"] == 0.5
    assert m["assinatura_f3_ausencia_falso_negativo"] == 0
    assert m["assinatura_f3_ausencia_falso_positivo"] == 1


# --- Fase 1 em codigo: chaves geradas contra a lista fechada ---------------

IDENTIDADE = {"entidade": "acme", "entidade_nome": "Acme"}


def test_candidato_identico_as_entradas_esperadas_zera_intrusas_e_cobre_tudo() -> None:
    mapping = {
        "g.dados[empresa=acme].valores[papel=ref].valor": _entrada(),
        "g.dados[empresa=acme].valores[papel=ref].periodo": _entrada(),
    }
    m = _m(expected_entries_metrics(mapping, CONTRATO, IDENTIDADE))
    assert m["assinatura_f1_entradas_obrigatorias_cobertas"] == 1.0
    assert m["assinatura_f1_chaves_fora_das_esperadas"] == 0
    assert m["assinatura_f1_contexto_irmao_presente"] == 1.0
    assert m["assinatura_f1_filtro_valor_identidade_correto"] == 1.0


def test_nome_no_lugar_do_slug_conta_como_intrusa_e_identidade_errada() -> None:
    """O que a estrutura da fase 1 antiga aceitava (Acme e valida) agora e medido."""
    mapping = {
        "g.dados[empresa=Acme].valores[papel=ref].valor": _entrada(),
        "g.dados[empresa=Acme].valores[papel=ref].periodo": _entrada(),
    }
    m = _m(expected_entries_metrics(mapping, CONTRATO, IDENTIDADE))
    assert m["assinatura_f1_chaves_fora_das_esperadas"] == 2
    assert m["assinatura_f1_filtro_valor_identidade_correto"] == 0.0
    assert m["assinatura_f1_entradas_obrigatorias_cobertas"] == 0.0


def test_valor_sem_o_contexto_irmao_e_chave_de_item_extra_sao_contados() -> None:
    mapping = {
        "g.dados[empresa=acme].valores[papel=ref].valor": _entrada(),
        "g.dados[empresa=acme].valores[papel=ant].valor": _entrada(coluna=2),
        "g.dados[empresa=acme].valores[papel=ant].periodo": _entrada(coluna=2),
        "g.dados[empresa=acme].empresa": {"tipo_origem": "valor_fixo", "valor_fixo": "Acme"},
    }
    m = _m(expected_entries_metrics(mapping, CONTRATO, IDENTIDADE))
    assert m["assinatura_f1_chaves_fora_das_esperadas"] == 1
    assert m["assinatura_f1_contexto_irmao_presente"] == 0.5
    # ref.periodo (obrigatoria) falta: 1 de 2 obrigatorias cobertas.
    assert m["assinatura_f1_entradas_obrigatorias_cobertas"] == 0.5


def test_sem_identidade_para_fechar_as_chaves_nao_ha_metrica() -> None:
    assert expected_entries_metrics({"g.dados[empresa=acme].valores[papel=ref].valor": _entrada()}, CONTRATO, {}) == []


# ---------------------------------------------------------------------------
# Fase 2 — estrutura_tabelas do payload contra o gabarito
# ---------------------------------------------------------------------------

GABARITO_F2 = {
    "artefatos_esperados_por_requisito": {"g.dados.valores.valor": ["tables/t1.json"]},
    "ancoragens": {
        "g.dados.valores.valor": [
            {"seletores": {"empresa": "acme", "papel": "ref"}, "arquivo_origem": "tables/t1.json", "indice_coluna": 1},
            {"seletores": {"empresa": "acme", "papel": "ant"}, "arquivo_origem": "tables/t1.json", "indice_coluna": 2},
            {"seletores": {"empresa": "acme", "papel": "ano"}, "arquivo_origem": "tables/t1.json", "indice_coluna": 4},
        ]
    },
}


def test_f2_colunas_resolvidas_pelo_contrato_conferidas_com_o_gabarito() -> None:
    estrutura = {
        "tables/t1.json": {
            "cabecalho_lido": True,
            "papel_por_coluna": {"papel": {"1": "ref", "3": "ant"}},
            "papeis_nao_resolvidos": {"papel": ["ano"]},
        },
        "tables/t9.json": {"cabecalho_lido": False},
    }
    m = _m(column_role_metrics(estrutura, GABARITO_F2))
    assert m["assinatura_f2_estrutura_tabela_lida"] == 1.0
    # 3 papeis do gabarito derivaveis; 2 resolvidos pelo codigo; 1 deles certo.
    assert m["assinatura_f2_papel_coluna_origem_contrato"] == 2 / 3
    assert m["assinatura_f2_papel_coluna_correto"] == 0.5


def test_f2_sem_papel_derivavel_so_a_leitura_da_estrutura_e_medida() -> None:
    estrutura = {"tables/t1.json": {"cabecalho_lido": False}}
    m = _m(column_role_metrics(estrutura, GABARITO_F2))
    assert m == {"assinatura_f2_estrutura_tabela_lida": 0.0}
    assert column_role_metrics({}, GABARITO_F2) == []


COLECAO = "grupo.por_modalidade"


def _resolvido(*itens):
    return {"grupo": {"por_modalidade": list(itens)}}


def _gabarito_resolvido(*observacoes, colecao=COLECAO):
    return {"observacoes_resolvidas": {colecao: list(observacoes)}}


def _obs(modalidade, agente, **campos):
    return {"contexto": {"modalidade": modalidade, "agente": agente}, "campos": campos}


def test_resolvido_confere_item_por_contexto_sem_acento_nem_caixa() -> None:
    resolvido = _resolvido(
        {"modalidade": "construcao", "agente": "ITAÚ UNIBANCO", "volume": 1971.4, "unidades": 5329.0},
    )
    gabarito = _gabarito_resolvido(_obs("Construcao", "Itau Unibanco", volume=1971.4, unidades=5329))
    m = _m(resolved_observation_metrics(resolvido, gabarito))
    assert m["assinatura_resolvido_observacoes_corretas"] == 1.0
    assert m["assinatura_resolvido_observacoes_erradas"] == 0
    assert m["assinatura_resolvido_observacoes_ausentes"] == 0


def test_resolvido_item_existe_com_valor_diferente_e_errado_nao_ausente() -> None:
    resolvido = _resolvido({"modalidade": "construcao", "agente": "CAIXA", "volume": 2378.1})
    gabarito = _gabarito_resolvido(_obs("construcao", "CAIXA", volume=2387.1))
    m = _m(resolved_observation_metrics(resolvido, gabarito))
    assert m["assinatura_resolvido_observacoes_corretas"] == 0.0
    assert m["assinatura_resolvido_observacoes_erradas"] == 1
    assert m["assinatura_resolvido_observacoes_ausentes"] == 0


def test_resolvido_modalidade_que_nao_saiu_conta_como_ausente() -> None:
    """Coleção que perde duas das três tabelas: o gabarito acusa o que sumiu."""
    resolvido = _resolvido({"modalidade": "construcao", "agente": "CAIXA", "volume": 1.0})
    gabarito = _gabarito_resolvido(
        _obs("construcao", "CAIXA", volume=1.0),
        _obs("aquisicao", "CAIXA", volume=2.0),
        _obs("total", "CAIXA", volume=3.0),
    )
    metricas = resolved_observation_metrics(resolvido, gabarito)
    m = _m(metricas)
    assert m["assinatura_resolvido_observacoes_corretas"] == 1 / 3
    assert m["assinatura_resolvido_observacoes_ausentes"] == 2
    assert metricas[0].metadata["por_colecao"][COLECAO] == {"corretas": 1, "erradas": 0, "ausentes": 2}


def test_resolvido_sem_contexto_so_confere_presenca_do_valor() -> None:
    resolvido = {"serie": [{"rotulo": "x", "saldo": 10.0}, {"rotulo": "y", "saldo": 20.0}]}
    gabarito = {
        "observacoes_resolvidas": {
            "serie": [{"campos": {"saldo": 20}}, {"campos": {"saldo": 30}}],
        }
    }
    m = _m(resolved_observation_metrics(resolvido, gabarito))
    assert m["assinatura_resolvido_observacoes_corretas"] == 0.5
    # sem contexto nao ha como dizer "errada": o valor simplesmente nao esta la.
    assert m["assinatura_resolvido_observacoes_erradas"] == 0
    assert m["assinatura_resolvido_observacoes_ausentes"] == 1


def test_resolvido_tolerancia_e_contexto_aninhado() -> None:
    resolvido = {"serie": [{"periodo": {"rotulo": "Jan"}, "volume": 12125.0}]}
    gabarito = {
        "observacoes_resolvidas": {
            "serie": [{"contexto": {"periodo.rotulo": "jan"}, "campos": {"volume": 12125.32}, "tolerancia": 1}],
        }
    }
    assert _m(resolved_observation_metrics(resolvido, gabarito))["assinatura_resolvido_observacoes_corretas"] == 1.0
    sem_tolerancia = {"observacoes_resolvidas": {"serie": [{"contexto": {"periodo.rotulo": "jan"}, "campos": {"volume": 12125.32}}]}}
    assert _m(resolved_observation_metrics(resolvido, sem_tolerancia))["assinatura_resolvido_observacoes_erradas"] == 1


def test_resolvido_item_a_mais_nao_penaliza_e_colecao_ausente_nao_quebra() -> None:
    resolvido = _resolvido({"modalidade": "construcao", "agente": "CAIXA", "volume": 1.0}, {"modalidade": "x", "agente": "Y", "volume": 9.0})
    gabarito = {
        "observacoes_resolvidas": {
            COLECAO: [_obs("construcao", "CAIXA", volume=1.0)],
            "outro.caminho": [{"campos": {"v": 1}}],
        }
    }
    m = _m(resolved_observation_metrics(resolvido, gabarito))
    assert m["assinatura_resolvido_observacoes_corretas"] == 0.5
    assert m["assinatura_resolvido_observacoes_ausentes"] == 1


def test_resolvido_sem_observacoes_no_gabarito_nao_ha_metrica() -> None:
    assert resolved_observation_metrics(_resolvido(), {}) == []
    assert resolved_observation_metrics(_resolvido(), {"observacoes_resolvidas": {COLECAO: []}}) == []

