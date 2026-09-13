"""Duas regras que o resolvedor ja pressupunha e a validacao nao cobrava.

1. ``celula_de_tabela`` sem ``seletor_linha.valor_aceito`` passa na validacao e
   resolve para ``null``: o resolvedor so aceita a linha pelo rotulo, e o indice
   e uma dica. O Itau publicou 29 campos nulos por isso.
2. Um filtro ``[periodo=jun/26&recorte=consolidado]`` casava com a gramatica e
   produzia um seletor cujo valor literal era ``jun/26&recorte=consolidado``.
"""

from __future__ import annotations

import pytest

from document_processing.domain.fallback.candidate_validation import (
    FallbackCandidateValidationService,
)
from document_processing.domain.fallback.models import LayoutSignatureCandidate
from document_processing.domain.layouts.paths import (
    normalize_mapping_path,
    parse_mapping_path,
)

_descrever = FallbackCandidateValidationService._describe_bad_mapping_path
_validar_tabelas = FallbackCandidateValidationService._validate_table_mappings_use_indices_only


def _candidato(seletor_linha: dict | None) -> LayoutSignatureCandidate:
    entrada = {
        "tipo_origem": "celula_de_tabela",
        "arquivo_origem": "tables/table001.json",
        "seletor_coluna": {"indice_coluna_esperado": 1},
    }
    if seletor_linha is not None:
        entrada["seletor_linha"] = seletor_linha
    return LayoutSignatureCandidate.model_validate(
        {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "criacao_inicial_layout",
            "document_id": "doc",
            "execution_id_origem": "exec",
            "mapeamento_canonico": {"serie.pontos[id=x].valores[periodo=2T26].valor": entrada},
        }
    )


@pytest.mark.parametrize(
    "seletor_linha",
    [
        None,
        {"indice_linha_esperado": 2},
        {"indice_linha_esperado": 2, "valor_aceito": ""},
        {"indice_linha_esperado": 2, "valor_aceito": "   "},
    ],
)
def test_celula_sem_valor_aceito_e_reprovada(seletor_linha):
    with pytest.raises(RuntimeError) as excecao:
        _validar_tabelas(_candidato(seletor_linha), schema_paths=set())
    mensagem = str(excecao.value)
    assert "seletor_linha.valor_aceito" in mensagem
    assert "indice_linha_esperado sozinho nao basta" in mensagem


def test_celula_com_valor_aceito_passa_sem_indice():
    _validar_tabelas(
        _candidato({"valor_aceito": "Resultado Recorrente Gerencial"}),
        schema_paths=set(),
    )


def test_cabecalho_de_tabela_nao_exige_seletor_linha():
    candidato = LayoutSignatureCandidate.model_validate(
        {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "criacao_inicial_layout",
            "document_id": "doc",
            "execution_id_origem": "exec",
            "mapeamento_canonico": {
                "serie.pontos[id=x].valores[periodo=2T26].periodo": {
                    "tipo_origem": "cabecalho_de_tabela",
                    "arquivo_origem": "tables/table001.json",
                    "seletor_coluna": {"indice_coluna_esperado": 1},
                }
            },
        }
    )
    _validar_tabelas(candidato, schema_paths=set())


def test_gramatica_recusa_condicoes_concatenadas_por_e_comercial():
    with pytest.raises(ValueError, match="'&'"):
        parse_mapping_path("dados[indicador=npl].valores[periodo=jun/26&recorte=consolidado].valor")


def test_gramatica_continua_aceitando_barra_e_espaco_no_valor():
    tokens = parse_mapping_path("dados[indicador=npl].valores[periodo=jun/26 ].valor")
    assert tokens[1]["selector"] == ("periodo", "jun/26")
    assert normalize_mapping_path("dados[indicador=npl].valores[periodo=jun/26].valor") == (
        "dados.valores.valor"
    )


def test_diagnose_nomeia_o_e_comercial_em_vez_de_indice_posicional():
    path = "dados[indicador=npl].valores[periodo=jun/26&recorte=consolidado].valor"
    mensagem = _descrever(path)
    assert "concatena condicoes com '&'" in mensagem
    assert "indice posicional" not in mensagem
    assert "acumula" not in mensagem
    assert path in mensagem


def test_validador_de_candidato_usa_a_diagnose_do_e_comercial():
    candidato = {
        "tipo_artefato": "layout_signature_candidato",
        "status_layout": "candidato",
        "escopo_correcao": "criacao_inicial_layout",
        "document_id": "doc",
        "execution_id_origem": "exec",
        "mapeamento_canonico": {
            "indicadores_percentuais.dados[indicador=npl].valores[periodo=x&recorte=y].valor": {
                "tipo_origem": "valor_fixo",
                "valor_fixo": "x",
            }
        },
    }
    contexto = {
        "contrato_semantico_relevante": {
            "estrutura_schema_saida": {"campos_raiz": ["indicadores_percentuais"]}
        }
    }
    with pytest.raises(RuntimeError, match="concatena condicoes com '&'"):
        FallbackCandidateValidationService().validate_candidate_layout(candidato, contexto)
