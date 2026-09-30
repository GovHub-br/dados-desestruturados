"""A entrada de contexto fabricada pela LLM tem que sair do candidato.

Complementa test_optional_observation_context_orphans.py (domain): aqui o
alvo e a chave real de mapeamento_canonico que precisa ser removida do
candidato antes de ele seguir para a revalidacao -- e nao so a deteccao da
ausencia.
"""

from __future__ import annotations

from document_processing.application.use_cases.fallback.trace_persistence import (
    FallbackTracePersistenceMixin,
)
from document_processing.domain.fallback.models import LayoutSignatureCandidate

# Chave real de mapeamento_canonico, com os filtros [chave=valor] do candidato.
MAPPING_KEY_PERIODO = (
    "indicadores_razao.dados[indicador=alavancagem_divida_liquida_ebitda]"
    ".valores[papel_periodo=periodo_referencia].periodo"
)
# Como aparece em "missing" (path, seletores): sem filtro de array, igual ao
# que optional_mapping_observations_not_mapped devolve a partir do requisito
# declarado no contrato.
PLAIN_PATH_VALOR = "indicadores_razao.dados.valores.valor"
PLAIN_PATH_PERIODO = "indicadores_razao.dados.valores.periodo"
SELETORES = {
    "indicador": "alavancagem_divida_liquida_ebitda",
    "papel_periodo": "periodo_referencia",
}


def test_remove_apenas_a_chave_orfa_e_preserva_o_resto():
    candidato = LayoutSignatureCandidate.model_validate(
        {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "criacao_inicial_layout",
            "document_id": "doc-1",
            "execution_id_origem": "dag_detecta_pdf_e_extrai__prio__2T26",
            "base_layout_signature": None,
            "mapeamento_canonico": {
                MAPPING_KEY_PERIODO: {
                    "tipo_origem": "campo_derivado",
                    "campo_origem": "nao_existe.em.lugar.nenhum",
                    "obrigatorio": True,
                },
                "indicadores_monetarios.dados[indicador=receita_liquida]"
                ".valores[papel_periodo=periodo_referencia].valor": {
                    "tipo_origem": "celula_de_tabela",
                    "arquivo_origem": "tables/table010.json",
                    "obrigatorio": True,
                },
            },
        }
    )
    missing = [(PLAIN_PATH_VALOR, SELETORES), (PLAIN_PATH_PERIODO, SELETORES)]

    orfas = FallbackTracePersistenceMixin._orphan_context_mapping_keys(
        candidate=candidato, missing=missing
    )

    assert orfas == {MAPPING_KEY_PERIODO}


def test_sem_entrada_fabricada_nao_ha_nada_para_remover():
    candidato = LayoutSignatureCandidate.model_validate(
        {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "criacao_inicial_layout",
            "document_id": "doc-1",
            "execution_id_origem": "dag_detecta_pdf_e_extrai__prio__2T26",
            "base_layout_signature": None,
            "mapeamento_canonico": {
                "indicadores_monetarios.dados[indicador=receita_liquida]"
                ".valores[papel_periodo=periodo_referencia].valor": {
                    "tipo_origem": "celula_de_tabela",
                    "arquivo_origem": "tables/table010.json",
                    "obrigatorio": True,
                },
            },
        }
    )
    missing = [(PLAIN_PATH_VALOR, SELETORES), (PLAIN_PATH_PERIODO, SELETORES)]

    orfas = FallbackTracePersistenceMixin._orphan_context_mapping_keys(
        candidate=candidato, missing=missing
    )

    assert orfas == set()
