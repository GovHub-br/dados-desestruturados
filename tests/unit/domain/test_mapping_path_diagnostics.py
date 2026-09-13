"""Testes das mensagens de erro do laco de reparo.

O laco so converge se a mensagem nomear o defeito real. Reportar um path
incompleto como "fora da unidade semantica" manda a LLM procurar o erro onde
ele nao esta, e ela repete a mesma classe de falha ate esgotar as tentativas.
"""

from __future__ import annotations

import pytest

from document_processing.domain.fallback.candidate_validation import (
    FallbackCandidateValidationService,
)

_descrever = FallbackCandidateValidationService._describe_bad_mapping_path


def test_indice_posicional_e_nomeado_como_tal():
    mensagem = _descrever("serie.observacoes[0].valor")
    assert "indice posicional" in mensagem
    assert "[0]" in mensagem


def test_dois_filtros_no_mesmo_segmento_nao_viram_indice_posicional():
    """O caso do Santander: nao havia indice nenhum no path recusado."""
    mensagem = _descrever("dados.valores[indicador=npl][recorte=consolidado]")
    assert "acumula 2 filtros" in mensagem
    assert "indice posicional" not in mensagem


def test_filtro_sem_chave_e_nomeado_como_tal():
    mensagem = _descrever("dados[npl].valores.valor")
    assert "filtro sem chave" in mensagem


@pytest.mark.parametrize(
    "path",
    ["dados.valores[0].valor", "dados.valores[indicador=npl][x=y]", "dados[npl].v"],
)
def test_toda_mensagem_repete_o_path_recusado(path: str):
    assert path in _descrever(path)


def test_path_incompleto_nao_e_reportado_como_outra_unidade():
    """O Santander recebeu "fora da unidade" por um path que estava dentro dela."""
    from document_processing.domain.fallback.mapping_plan import MappingUnit

    unidade = MappingUnit(
        id="indicadores_percentuais",
        root_path="indicadores_percentuais",
        requirements=(),
        mapping_paths=("indicadores_percentuais.dados.valores.valor",),
        subschema={},
    )
    fragmento = {
        "tipo_artefato": "fragmento_layout_signature",
        "unidade_mapeamento": "indicadores_percentuais",
        "mapeamento_canonico": {
            "indicadores_percentuais.dados[indicador=npl].valores": {
                "tipo_origem": "valor_fixo",
                "valor_fixo": "x",
            }
        },
    }
    with pytest.raises(RuntimeError) as excecao:
        FallbackCandidateValidationService().validate_layout_fragment(
            fragmento, unit=unidade, fallback_problem_context={}
        )
    mensagem = str(excecao.value)
    assert "parou antes do campo terminal" in mensagem
    assert "fora da unidade semantica" not in mensagem


def test_path_de_outra_unidade_continua_sendo_reportado_como_tal():
    from document_processing.domain.fallback.mapping_plan import MappingUnit

    unidade = MappingUnit(
        id="indicadores_percentuais",
        root_path="indicadores_percentuais",
        requirements=(),
        mapping_paths=("indicadores_percentuais.dados.valores.valor",),
        subschema={},
    )
    fragmento = {
        "tipo_artefato": "fragmento_layout_signature",
        "unidade_mapeamento": "indicadores_percentuais",
        "mapeamento_canonico": {
            "indicadores_monetarios.dados.valores.valor": {
                "tipo_origem": "valor_fixo",
                "valor_fixo": "x",
            }
        },
    }
    with pytest.raises(RuntimeError, match="fora da unidade semantica"):
        FallbackCandidateValidationService().validate_layout_fragment(
            fragmento, unit=unidade, fallback_problem_context={}
        )
