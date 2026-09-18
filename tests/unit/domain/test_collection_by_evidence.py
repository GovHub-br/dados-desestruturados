"""Colecao por evidencia: arrays cuja chave de item vem do artefato.

Reproduz o caso do Santander (release exp-prereq-fase0.1): a LLM respondeu uma
unica ``linhas_de_tabela`` sobre ``dados[indicador=x].valores`` cobrindo as cinco
linhas do grafico, exatamente como o prompt pede, e o validador de fragmento
rejeitava por "parou antes do campo terminal". O reparo forcava a expansao em
uma celula por linha, e a primeira resposta aceita trazia um unico periodo.

Nomes de campo aqui sao genericos: o codigo nao pode conhecer um dominio.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from document_processing.application.use_cases.resolution.resolve_schema import (
    SchemaResolutionService,
)
from document_processing.domain.fallback.candidate_validation import (
    FallbackCandidateValidationService,
)
from document_processing.domain.fallback.mapping_plan import MappingPlanService
from document_processing.domain.observability.signature_evaluation import anchoring_metrics

CONTRATO_CONTEXTO = {
    "contrato_semantico": {
        "requisitos_mapeamento": {
            "campos_obrigatorios": [
                {
                    "path": "serie.dados.valores.valor",
                    "observacoes_obrigatorias": [
                        {
                            "seletores": {"indicador": "taxa_a"},
                            "campos_contexto_obrigatorios": ["periodo", "recorte"],
                        },
                        {
                            "seletores": {"indicador": "taxa_b"},
                            "campos_contexto_obrigatorios": ["periodo", "recorte"],
                            "obrigatorio": False,
                        },
                    ],
                }
            ]
        }
    },
    "estrutura_schema_saida": {
        "campos_raiz": ["serie"],
        "paths_permitidos": [
            "serie",
            "serie.dados",
            "serie.dados.indicador",
            "serie.dados.valores",
            "serie.dados.valores.periodo",
            "serie.dados.valores.recorte",
            "serie.dados.valores.valor",
        ],
        "arrays_que_exigem_seletor": ["serie.dados", "serie.dados.valores"],
        "chaves_de_item": {"serie.dados": "indicador", "serie.dados.valores": "periodo"},
        "origem_das_chaves": {
            "serie.dados": "seletor_observacao",
            "serie.dados.valores": "evidencia",
        },
    },
}

CHAVE_COLECAO = "serie.dados[indicador=taxa_a].valores"

FRAGMENTO_COLECAO = {
    "tipo_artefato": "fragmento_layout_signature",
    "unidade_mapeamento": "serie",
    "campos_nao_mapeados": [],
    "mapeamento_canonico": {
        CHAVE_COLECAO: {
            "tipo_origem": "linhas_de_tabela",
            "arquivo_origem": "charts/chart001.json",
            "segmentos": [
                {
                    "linha_inicial": 0,
                    "linha_final": 4,
                    "valores_por_segmento": {"recorte": "consolidado"},
                }
            ],
            "campos": [
                {"caminho_saida": "periodo", "indice_coluna": 0},
                {"caminho_saida": "valor", "indice_coluna": 2, "tipo": "numero"},
            ],
            "obrigatorio": True,
        }
    },
    "fontes_relevantes": {},
    "metadados_estruturais_evidencia": {},
}

CONTEXTO_FALLBACK = {
    "escopo_permitido": "criacao_inicial_layout",
    "fallback_context": {"document_id": "doc-1", "execution_id": "execution-1"},
    "contrato_semantico_relevante": CONTRATO_CONTEXTO,
    "_paths_fixos_do_contrato": [],
}

LINHAS = [
    ["Jun/25", "4.0", "2.6", "1.5"],
    ["Set/25", "4.2", "2.8", "1.6"],
    ["Dez/25", "4.6", "3.1", "1.7"],
    ["Mar/26", "5.0", "3.3", "1.6"],
    ["Jun/26", "5.1", "3.3", "1.6"],
]


def _unidade():
    return MappingPlanService().build(CONTRATO_CONTEXTO)[0]


def test_plano_expoe_colecao_para_array_com_chave_vinda_da_evidencia():
    unidade = _unidade()
    assert unidade.collection_paths == ("serie.dados.valores",)
    assert unidade.payload()["colecoes_por_evidencia"] == ["serie.dados.valores"]
    assert "serie.dados.valores" in unidade.subschema["paths_permitidos"]
    # Os paths de mapeamento continuam terminais: uma celula no array segue invalida.
    assert "serie.dados.valores" not in unidade.mapping_paths


def test_plano_nao_expoe_colecao_quando_a_chave_e_seletor_do_contrato():
    contexto = json.loads(json.dumps(CONTRATO_CONTEXTO))
    contexto["estrutura_schema_saida"]["origem_das_chaves"]["serie.dados.valores"] = (
        "seletor_observacao"
    )
    unidade = MappingPlanService().build(contexto)[0]
    assert unidade.collection_paths == ()
    assert "colecoes_por_evidencia" not in unidade.payload()
    assert "serie.dados.valores" not in unidade.subschema["paths_permitidos"]


def test_fragmento_com_colecao_por_evidencia_e_aceito_sem_reparo():
    validado = FallbackCandidateValidationService().validate_layout_fragment(
        FRAGMENTO_COLECAO, unit=_unidade(), fallback_problem_context=CONTEXTO_FALLBACK
    )
    assert validado.mapeamento_canonico[CHAVE_COLECAO].tipo_origem == "linhas_de_tabela"


def test_colecao_sem_campo_de_contexto_obrigatorio_continua_rejeitada():
    fragmento = json.loads(json.dumps(FRAGMENTO_COLECAO))
    fragmento["mapeamento_canonico"][CHAVE_COLECAO]["campos"] = [
        {"caminho_saida": "valor", "indice_coluna": 2, "tipo": "numero"}
    ]
    with pytest.raises(RuntimeError, match="serie.dados.valores.periodo"):
        FallbackCandidateValidationService().validate_layout_fragment(
            fragmento, unit=_unidade(), fallback_problem_context=CONTEXTO_FALLBACK
        )


def test_celula_no_path_do_array_continua_incompleta():
    fragmento = json.loads(json.dumps(FRAGMENTO_COLECAO))
    fragmento["mapeamento_canonico"][CHAVE_COLECAO] = {
        "tipo_origem": "celula_de_tabela",
        "arquivo_origem": "charts/chart001.json",
        "seletor_linha": {"coluna_rotulo": 0, "valor_aceito": "Jun/26"},
        "seletor_coluna": {"indice_coluna_esperado": 2},
        "obrigatorio": True,
    }
    with pytest.raises(RuntimeError, match="parou antes do campo terminal"):
        FallbackCandidateValidationService().validate_layout_fragment(
            fragmento, unit=_unidade(), fallback_problem_context=CONTEXTO_FALLBACK
        )


def test_colecao_com_campo_fora_da_unidade_e_rejeitada():
    fragmento = json.loads(json.dumps(FRAGMENTO_COLECAO))
    fragmento["mapeamento_canonico"][CHAVE_COLECAO]["campos"].append(
        {"caminho_saida": "instituicao", "indice_coluna": 1}
    )
    with pytest.raises(RuntimeError, match="fora da unidade"):
        FallbackCandidateValidationService().validate_layout_fragment(
            fragmento, unit=_unidade(), fallback_problem_context=CONTEXTO_FALLBACK
        )


def test_resolvedor_preenche_a_colecao_sob_o_item_filtrado():
    contrato = {
        "schema_saida": {
            "serie": {
                "dados": [
                    {
                        "indicador": "string",
                        "valores": [
                            {"periodo": "string", "recorte": "string", "valor": "number"}
                        ],
                    }
                ]
            }
        }
    }
    with TemporaryDirectory() as directory:
        raiz = Path(directory)
        (raiz / "charts").mkdir()
        (raiz / "charts" / "chart001.json").write_text(
            json.dumps({"schema": ["Data", "PF", "Total", "PJ"], "rows": LINHAS})
        )
        resolvido = SchemaResolutionService().resolve_canonical_mapping(
            loaded={
                "contrato_semantico": contrato,
                "layout_signature": {
                    "mapeamento_canonico": FRAGMENTO_COLECAO["mapeamento_canonico"]
                },
                "extraction_root": raiz,
            },
            validation={"status_compatibilidade": {"status": "compativel"}},
        )
    dados = resolvido["schema_saida"]["serie"]["dados"]
    assert [item["indicador"] for item in dados] == ["taxa_a"]
    assert [(v["periodo"], v["valor"], v["recorte"]) for v in dados[0]["valores"]] == [
        ("Jun/25", 2.6, "consolidado"),
        ("Set/25", 2.8, "consolidado"),
        ("Dez/25", 3.1, "consolidado"),
        ("Mar/26", 3.3, "consolidado"),
        ("Jun/26", 3.3, "consolidado"),
    ]


def _gabarito() -> dict:
    return {
        "ancoragens": {
            "serie.dados.valores.valor": [
                {
                    "seletores": {"indicador": "taxa_a", "periodo": linha[0]},
                    "arquivo_origem": "charts/chart001.json",
                    "indice_linha": indice,
                    "rotulo_linha": linha[0],
                    "indice_coluna": 2,
                }
                for indice, linha in enumerate(LINHAS)
            ]
        }
    }


def _por_celula() -> dict:
    return {
        f"serie.dados[indicador=taxa_a].valores[periodo={linha[0]}].valor": {
            "tipo_origem": "celula_de_tabela",
            "arquivo_origem": "charts/chart001.json",
            "seletor_linha": {
                "coluna_rotulo": 0,
                "valor_aceito": linha[0],
                "indice_linha_esperado": indice,
            },
            "seletor_coluna": {"indice_coluna_esperado": 2},
        }
        for indice, linha in enumerate(LINHAS)
    }


def test_harness_pontua_a_colecao_como_as_celulas_equivalentes():
    def _valores(mapeamento: dict) -> dict[str, float]:
        return {m.name: round(m.value, 3) for m in anchoring_metrics(mapeamento, _gabarito())}

    por_celula = _valores(_por_celula())
    por_colecao = _valores(FRAGMENTO_COLECAO["mapeamento_canonico"])
    assert por_celula == por_colecao
    assert por_colecao["assinatura_f3_rotulo_linha_correto"] == 1.0
    assert por_colecao["assinatura_f3_ausencia_falso_negativo"] == 0.0


def test_harness_penaliza_linha_do_gabarito_fora_da_faixa_da_colecao():
    mapeamento = json.loads(json.dumps(FRAGMENTO_COLECAO["mapeamento_canonico"]))
    mapeamento[CHAVE_COLECAO]["segmentos"][0]["linha_final"] = 2
    valores = {m.name: round(m.value, 3) for m in anchoring_metrics(mapeamento, _gabarito())}
    assert valores["assinatura_f3_rotulo_linha_correto"] == 0.6
    assert valores["assinatura_f3_arquivo_origem_correto"] == 1.0
