"""Observacao opcional sem valor comprovado nao pode exigir o proprio contexto.

Regressao: a PRIO nao publica alavancagem_divida_liquida_ebitda como celula
isolada (so em texto corrido de destaques). A observacao e opcional e o
candidato declarou a ausencia corretamente em campos_nao_mapeados, mas a LLM
precisou inventar uma origem para o campo de contexto "periodo" da mesma
observacao so para responder a exigencia -- e essa entrada fabricada, com
obrigatorio=true, e o que barrava a publicacao na revalidacao.
"""

from __future__ import annotations

from document_processing.domain.fallback.candidate_validation import (
    FallbackCandidateValidationService,
)
from document_processing.domain.fallback.models import LayoutSignatureCandidate

CONTRATO = {
    "identificacao": {"nome": "petroleo_gas", "versao": "1.0.2"},
    "contrato_semantico": {
        "entidades": {},
        "metricas": {},
        "requisitos_mapeamento": {
            "campos_obrigatorios": [
                {
                    "path": "indicadores_razao.dados.valores.valor",
                    "observacoes_obrigatorias": [
                        {
                            "seletores": {
                                "indicador": "alavancagem_divida_liquida_ebitda",
                                "papel_periodo": "periodo_referencia",
                            },
                            "campos_contexto_obrigatorios": ["periodo"],
                            "obrigatorio": False,
                        }
                    ],
                }
            ],
        },
    },
    "estrutura_schema_saida": {
        "campos_raiz": ["indicadores_razao"],
        "paths_permitidos": [
            "indicadores_razao",
            "indicadores_razao.dados",
            "indicadores_razao.dados.valores",
            "indicadores_razao.dados.valores.valor",
            "indicadores_razao.dados.valores.periodo",
        ],
        "arrays_que_exigem_seletor": [
            "indicadores_razao.dados",
            "indicadores_razao.dados.valores",
        ],
    },
}

SELETORES_ALAVANCAGEM = {
    "indicador": "alavancagem_divida_liquida_ebitda",
    "papel_periodo": "periodo_referencia",
}

# Como o requisito declara no contrato: sem filtro de array, e assim que
# aparece em "missing" (path, seletores).
PLAIN_PATH_VALOR = "indicadores_razao.dados.valores.valor"
PLAIN_PATH_PERIODO = "indicadores_razao.dados.valores.periodo"

# Chave real de mapeamento_canonico, com os filtros [chave=valor] do candidato.
MAPPING_KEY_PERIODO = (
    "indicadores_razao.dados[indicador=alavancagem_divida_liquida_ebitda]"
    ".valores[papel_periodo=periodo_referencia].periodo"
)


def _candidato(*, com_periodo_fabricado: bool) -> LayoutSignatureCandidate:
    mapeamento: dict[str, dict] = {}
    if com_periodo_fabricado:
        mapeamento[MAPPING_KEY_PERIODO] = {
            "tipo_origem": "campo_derivado",
            "campo_origem": "nao_existe.em.lugar.nenhum",
            "obrigatorio": True,
        }
    return LayoutSignatureCandidate.model_validate(
        {
            "tipo_artefato": "layout_signature_candidato",
            "status_layout": "candidato",
            "escopo_correcao": "criacao_inicial_layout",
            "document_id": "doc-1",
            "execution_id_origem": "dag_detecta_pdf_e_extrai__prio__2T26",
            "base_layout_signature": None,
            "mapeamento_canonico": mapeamento,
            "campos_nao_mapeados": [
                {
                    "path": PLAIN_PATH_VALOR,
                    "seletores": SELETORES_ALAVANCAGEM,
                    "motivo": (
                        "Observacao declarada em campos_obrigatorios com "
                        "obrigatorio=false nao foi comprovada pelos artefatos selecionados."
                    ),
                    "artefatos_verificados": ["tables/table010.json"],
                    "obrigatorio": False,
                }
            ],
        }
    )


def test_contexto_de_observacao_ausente_entra_na_lista_mesmo_sem_valor():
    """Sem valor comprovado, o proprio path de valor e seus campos de contexto
    contam como ausencia opcional -- e o que a fase anterior nao fazia."""
    candidato = _candidato(com_periodo_fabricado=False)
    ausentes = FallbackCandidateValidationService.optional_mapping_observations_not_mapped(
        candidato, {"contrato_semantico_relevante": CONTRATO}
    )
    paths_ausentes = {path for path, _selectors in ausentes}
    assert PLAIN_PATH_VALOR in paths_ausentes
    assert PLAIN_PATH_PERIODO in paths_ausentes


def test_contexto_fabricado_pelo_candidato_ainda_e_reportado_como_orfao():
    """Mesmo quando o candidato mapeou o periodo, ele conta como ausencia:
    sem o valor da observacao, o contexto que o acompanha nao tem para que
    existir, e e essa entrada que a auditoria precisa sinalizar para remocao."""
    candidato = _candidato(com_periodo_fabricado=True)
    assert MAPPING_KEY_PERIODO in candidato.mapeamento_canonico

    ausentes = FallbackCandidateValidationService.optional_mapping_observations_not_mapped(
        candidato, {"contrato_semantico_relevante": CONTRATO}
    )
    paths_ausentes = {path for path, _selectors in ausentes}
    assert PLAIN_PATH_PERIODO in paths_ausentes
