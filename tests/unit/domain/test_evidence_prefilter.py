"""Fase 0: pre-filtro deterministico da evidencia a partir do contrato."""

from __future__ import annotations

from document_processing.domain.fallback.artifact_selection_validation import (
    ArtifactSelectionValidationError,
    ArtifactSelectionValidationService,
)
from document_processing.domain.fallback.evidence_prefilter import (
    artifact_full_text,
    candidate_paths_by_requirement,
    prefilter_inventory,
    prefilter_payload,
    run_prefilter,
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


ARTEFATOS = {
    # tabela grande: as 12 linhas nao tem nenhum termo -> sai depois da leitura
    "tables/t3.json": {"name": "Grande", "schema": ["a", "b"], "rows": [[f"linha {i}", str(i)] for i in range(12)]},
    # grafico que o resumo ja decide para grupo_b; lido so para grupo_a, sem termo
    "charts/c1.json": {"name": "Grafico Z", "schema": ["Period", "Rotulo Z"], "rows": [["1T26", "5"]]},
    # grafico sem rotulos no resumo: as linhas trazem o termo do grupo_b
    "charts/c2.json": {"name": "Sem nome util", "schema": ["Period", "v"], "rows": [["1T26", "Rótulo Z"]]},
}


def _loader(chamadas: list[str]):
    def load(path: str) -> str | None:
        chamadas.append(path)
        artefato = ARTEFATOS.get(path)
        return artifact_full_text(artefato) if artefato else None

    return load


def test_prefiltro_sem_leitor_mantem_amostra_incompleta() -> None:
    candidatos = prefilter_inventory(INVENTARIO, CONTRATO)
    a = {c.path: c.motivo for c in candidatos["raiz.grupo_a.dados.valores.valor"]}
    assert a["tables/t1.json"] == "termo_casado"
    assert "tables/t2.json" not in a, "tabela vista inteira sem termo sai"
    assert a["tables/t3.json"] == "amostra_incompleta"
    assert a["charts/c2.json"] == "amostra_incompleta", "grafico sem linhas nao pode ser excluido"
    b = {c.path: c.motivo for c in candidatos["raiz.grupo_b.dados.valores.valor"]}
    assert b["charts/c1.json"] == "termo_casado"


def test_leitura_completa_decide_o_que_o_resumo_nao_decidiu() -> None:
    chamadas: list[str] = []
    resultado = run_prefilter(INVENTARIO, CONTRATO, load_artifact_text=_loader(chamadas))
    a = {c.path: c for c in resultado.candidates["raiz.grupo_a.dados.valores.valor"]}
    b = {c.path: c for c in resultado.candidates["raiz.grupo_b.dados.valores.valor"]}
    assert "tables/t3.json" not in a and "tables/t3.json" not in b, "lida inteira sem termo: sai"
    assert "charts/c2.json" not in a, "grafico lido inteiro sem termo do grupo_a: sai"
    assert b["charts/c2.json"].motivo == "termo_casado"
    assert b["charts/c2.json"].fonte == "artefato_completo"
    assert "rotulo z" in b["charts/c2.json"].termos_casados
    assert a["tables/t1.json"].fonte == "resumo", "o que o resumo decide nao e relido"
    assert "charts/c1.json" not in a and b["charts/c1.json"].fonte == "resumo"
    # uma leitura por artefato, mesmo com dois requisitos
    assert sorted(chamadas) == ["charts/c1.json", "charts/c2.json", "tables/t3.json"]
    assert set(resultado.artefatos_lidos) == {"tables/t3.json", "charts/c1.json", "charts/c2.json"}
    assert resultado.excluidos_apos_leitura == ("tables/t3.json",), "c1 segue candidato de grupo_b"
    assert resultado.sem_leitura == ()


def test_artefato_ilegivel_volta_a_amostra_incompleta() -> None:
    resultado = run_prefilter(INVENTARIO, CONTRATO, load_artifact_text=lambda path: None)
    a = {c.path: c.motivo for c in resultado.candidates["raiz.grupo_a.dados.valores.valor"]}
    assert a["tables/t3.json"] == "amostra_incompleta"
    assert a["charts/c2.json"] == "amostra_incompleta"
    assert set(resultado.sem_leitura) == {"tables/t3.json", "charts/c1.json", "charts/c2.json"}
    assert resultado.artefatos_lidos == ()

    def explode(path: str) -> str | None:
        raise OSError("minio fora")

    resultado = run_prefilter(INVENTARIO, CONTRATO, load_artifact_text=explode)
    a = {c.path: c.motivo for c in resultado.candidates["raiz.grupo_a.dados.valores.valor"]}
    assert a["tables/t3.json"] == "amostra_incompleta", "erro de leitura nunca exclui"


def test_texto_do_artefato_completo_cobre_todas_as_celulas() -> None:
    texto = artifact_full_text(
        {"name": "Tab", "schema": ["Métrica", "2T26"], "rows": [["Número de Unidades", "10"], ["", "x"]]},
        item={"section_title": "Lançamentos"},
    )
    assert texto is not None
    for esperado in ("tab", "metrica", "2t26", "numero de unidades", "lancamentos"):
        assert esperado in texto
    assert artifact_full_text({"name": "sem rows"}) is None
    assert artifact_full_text("nao e dict") is None


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
    assert "selecao_prefiltro_leitura_completa" not in metricas, "sem bloco de leitura, sem metrica"


def test_metricas_com_leitura_completa() -> None:
    resultado = run_prefilter(INVENTARIO, CONTRATO, load_artifact_text=_loader([]))
    serializado = prefilter_payload(resultado.candidates)
    metricas = {
        m.name: m.value
        for m in evidence_prefilter_metrics(
            {
                "candidatos_por_requisito": serializado,
                "total_artefatos_inventario": 5,
                "leitura_completa": {
                    "artefatos_lidos": list(resultado.artefatos_lidos),
                    "excluidos_apos_leitura": list(resultado.excluidos_apos_leitura),
                    "sem_leitura": list(resultado.sem_leitura),
                },
            },
            selected_paths=["tables/t1.json", "charts/c2.json"],
        )
    }
    # grupo_a: so t1 (c1 e c2 lidos sem termo); grupo_b: c1 (resumo) + c2 (lido)
    assert metricas["selecao_candidatos_por_requisito"] == 1.5
    assert metricas["selecao_prefiltro_reducao"] == 0.4, "t2, t3 fora; t1, c1, c2 seguem"
    assert metricas["selecao_prefiltro_leitura_completa"] == 1.0
    assert metricas["selecao_escolha_dentro_do_prefiltro"] == 1.0, "lido por inteiro conta como termo casado"
