"""Fase 0: pre-filtro deterministico da evidencia a partir do contrato."""

from __future__ import annotations

from document_processing.domain.fallback.artifact_selection_validation import (
    ArtifactSelectionValidationError,
    ArtifactSelectionValidationService,
)
from document_processing.domain.fallback.evidence_prefilter import (
    candidate_paths_by_requirement,
    prefilter_inventory,
    prefilter_payload,
    search_criteria_by_requirement,
)
from document_processing.domain.fallback.models import LayoutArtifactSelection
from document_processing.domain.observability import evidence_prefilter_metrics

CONTRATO = {
    "contrato_semantico": {
        "entidades": {
            "recorte": {"dominio": ["consolidado"], "sinonimos": ["Total"]},
        },
        "metricas": {
            "grupo_a": {
                "indicadores": {
                    "ind_x": {"sinonimos": ["Rotulo X", "x alternativo"]},
                    "ind_y": {"sinonimos": ["Rotulo Y"]},
                }
            },
            "grupo_b": {"indicadores": {"ind_z": {"sinonimos": ["Rotulo Z"]}}},
        },
        "requisitos_mapeamento": {
            "campos_obrigatorios": [
                {
                    "path": "raiz.grupo_a.dados.valores.valor",
                    "observacoes_obrigatorias": [{"seletores": {"indicador": "ind_x"}}],
                },
                {
                    "path": "raiz.grupo_b.dados.valores.valor",
                    "observacoes_obrigatorias": [{"seletores": {"papel": "referencia"}}],
                },
            ]
        },
    }
}

INVENTARIO = [
    {"kind": "table", "path": "tables/t1.json", "name": "Tabela X", "schema": ["a"], "row_labels_sample": ["Rótulo X"], "row_count": 1},
    {"kind": "table", "path": "tables/t2.json", "name": "Outra", "schema": ["a"], "row_labels_sample": ["nada"], "row_count": 1},
    {"kind": "table", "path": "tables/t3.json", "name": "Grande", "schema": ["a"], "row_labels_sample": ["nada"], "row_count": 12},
    {"kind": "chart", "path": "charts/c1.json", "name": "Grafico Z", "schema": ["Period", "Rotulo Z"], "row_labels_sample": None},
    {"kind": "chart", "path": "charts/c2.json", "name": "Sem nome util", "schema": ["Period"], "row_labels_sample": None},
]


def test_termos_vem_do_indicador_selecionado_e_do_grupo_nomeado_no_path() -> None:
    criteria = search_criteria_by_requirement(CONTRATO)
    termos_a = criteria["raiz.grupo_a.dados.valores.valor"].termos
    assert "rotulo x" in termos_a and "x alternativo" in termos_a
    assert "rotulo y" not in termos_a, "indicador nao selecionado nao entra"
    termos_b = criteria["raiz.grupo_b.dados.valores.valor"].termos
    assert "rotulo z" in termos_b and "grupo b" in termos_b


def test_prefiltro_exclui_so_o_que_viu_inteiro_sem_termo() -> None:
    candidatos = prefilter_inventory(INVENTARIO, CONTRATO)
    a = {c.path: c.motivo for c in candidatos["raiz.grupo_a.dados.valores.valor"]}
    assert a["tables/t1.json"] == "termo_casado"
    assert "tables/t2.json" not in a, "tabela vista inteira sem termo sai"
    assert a["tables/t3.json"] == "amostra_incompleta"
    assert a["charts/c2.json"] == "amostra_incompleta", "grafico sem linhas nao pode ser excluido"
    b = {c.path: c.motivo for c in candidatos["raiz.grupo_b.dados.valores.valor"]}
    assert b["charts/c1.json"] == "termo_casado"


def test_validador_recusa_escolha_fora_dos_candidatos() -> None:
    payload = {
        "contrato_semantico_relevante": CONTRATO,
        "candidatos_por_requisito": prefilter_payload(prefilter_inventory(INVENTARIO, CONTRATO)),
    }
    selecao = LayoutArtifactSelection.model_validate(
        {
            "tipo_artefato": "selecao_artefatos_layout",
            "artifact_paths": [
                {
                    "path": "tables/t2.json",
                    "motivo": "x",
                    "coberturas": [{"campo_saida": "raiz.grupo_a.dados.valores.valor", "ancoras": ["nada"]}],
                }
            ]
        }
    )
    service = ArtifactSelectionValidationService()
    try:
        service.validate_coverage(
            artifact_selection=selecao,
            selection_payload=payload,
            loaded_artifacts={"tables/t2.json": {"rows": [["nada"]]}},
        )
    except ArtifactSelectionValidationError as exc:
        assert "candidatos do pre-filtro" in str(exc)
    else:
        raise AssertionError("escolha fora dos candidatos deveria ser recusada")


def test_metricas_do_prefiltro() -> None:
    serializado = prefilter_payload(prefilter_inventory(INVENTARIO, CONTRATO))
    assert candidate_paths_by_requirement(serializado)["raiz.grupo_a.dados.valores.valor"] == {
        "tables/t1.json",
        "tables/t3.json",
        "charts/c1.json",
        "charts/c2.json",
    }
    metricas = {
        m.name: m.value
        for m in evidence_prefilter_metrics(
            {"candidatos_por_requisito": serializado, "total_artefatos_inventario": 5},
            selected_paths=["tables/t1.json", "tables/t3.json"],
        )
    }
    assert metricas["selecao_candidatos_por_requisito"] == 3.5
    assert metricas["selecao_prefiltro_reducao"] == 0.2
    assert metricas["selecao_escolha_dentro_do_prefiltro"] == 0.5
