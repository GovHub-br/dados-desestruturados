"""Metricas por fase da assinatura de layout, definidas sobre contrato e gabarito."""

from __future__ import annotations

from document_processing.domain.observability.signature_evaluation import (
    anchoring_metrics,
    expected_entries_metrics,
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
