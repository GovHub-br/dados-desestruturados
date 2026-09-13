"""Teste do recorte de arrays por unidade de mapeamento.

Um array e ancestral do campo terminal exigido, nunca descendente. Testar a
direcao errada esvazia `arrays_que_exigem_seletor` e a LLM passa a receber
"nenhum array exige seletor" enquanto o validador exige seletor.
"""

from __future__ import annotations

from document_processing.domain.fallback.mapping_plan import MappingPlanService

CONTRATO = {
    "contrato_semantico": {
        "requisitos_mapeamento": {
            "campos_obrigatorios": [
                {
                    "path": "indicadores.dados.valores.valor",
                    "observacoes_obrigatorias": [
                        {
                            "seletores": {"indicador": "npl"},
                            "campos_contexto_obrigatorios": ["periodo"],
                        }
                    ],
                }
            ]
        }
    },
    "estrutura_schema_saida": {
        "campos_raiz": ["indicadores"],
        "paths_permitidos": [
            "indicadores.dados.valores.valor",
            "indicadores.dados.valores.periodo",
        ],
        "arrays_que_exigem_seletor": [
            "indicadores.dados",
            "indicadores.dados.valores",
        ],
    },
}


def test_subesquema_preserva_os_arrays_ancestrais():
    unidades = MappingPlanService().build(CONTRATO)
    assert len(unidades) == 1
    arrays = unidades[0].subschema["arrays_que_exigem_seletor"]
    assert arrays == ["indicadores.dados", "indicadores.dados.valores"]


def test_subesquema_ignora_array_de_outra_unidade():
    contrato = {
        **CONTRATO,
        "estrutura_schema_saida": {
            **CONTRATO["estrutura_schema_saida"],
            "arrays_que_exigem_seletor": [
                "indicadores.dados",
                "outra_raiz.dados",
            ],
        },
    }
    unidades = MappingPlanService().build(contrato)
    assert unidades[0].subschema["arrays_que_exigem_seletor"] == ["indicadores.dados"]
