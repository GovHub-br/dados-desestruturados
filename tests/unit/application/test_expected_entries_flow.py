"""Fase 1 no fluxo da DAG 3: as chaves fechadas viajam ate a LLM e voltam ao validador.

Cobre o caminho inteiro sem MinIO, LLM nem Airflow: identidade do documento ->
payload com entradas_esperadas -> mensagens -> validador chave a chave.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from document_processing.application.use_cases.fallback import prompt_sets
from document_processing.application.use_cases.fallback.candidate_json_generation import (
    CandidateJsonGenerationMixin,
)
from document_processing.application.use_cases.fallback.context_builder import (
    FallbackProblemContextBuilder,
)
from document_processing.application.use_cases.fallback.context_loading import (
    FallbackContextLoadingMixin,
)
from document_processing.application.use_cases.fallback.mapping_unit_generation import (
    MappingUnitGenerationMixin,
)
from document_processing.domain.fallback.candidate_validation import (
    FallbackCandidateValidationService,
)
from document_processing.domain.fallback.mapping_plan import MAPPING_PLAN_SERVICE

CONTRATOS = Path("infra/minio-bootstrap/contracts")
IDENTIDADE = {"entidade": "cury", "entidade_nome": "Cury", "periodo": "2T26"}
EXECUCAO = {"document_id": "doc-1", "execution_id": "exec-1", "manifest_key": "m", "entity_slug": "cury"}


@pytest.fixture(scope="module")
def contrato() -> dict[str, Any]:
    caminho = next((CONTRATOS / "construtoras" / "v1.9.0").glob("*.json"))
    return json.loads(caminho.read_text(encoding="utf-8"))


@pytest.fixture
def contexto(contrato: dict[str, Any]) -> dict[str, Any]:
    builder = FallbackProblemContextBuilder()
    projetado = builder._relevant_contract_context(contract=contrato, broken_fields=[])
    contexto = {
        "escopo_permitido": "criacao_inicial_layout",
        "fallback_context": EXECUCAO,
        "contrato_semantico_relevante": projetado,
        "inventario_extracao": {"resumo": {"items": []}},
        "identidade_documento": IDENTIDADE,
        "_paths_fixos_do_contrato": [],
        "layout_signature_base_ref": None,
    }
    contexto["llm_payloads"] = builder.build_llm_payloads(contexto)
    return contexto


@pytest.fixture(autouse=True)
def _sem_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLAS_PROMPTS_LANGFUSE_ENABLED", raising=False)
    prompt_sets.LANGFUSE_PROMPT_REGISTRY.limpar_cache()


def _celula(indice_coluna: int) -> dict[str, Any]:
    return {
        "tipo_origem": "celula_de_tabela",
        "arquivo_origem": "tables/table001.json",
        "seletor_linha": {"coluna_rotulo": 0, "valor_aceito": "Numero de Unidades", "indice_linha_esperado": 2},
        "seletor_coluna": {"indice_coluna_esperado": indice_coluna},
        "obrigatorio": True,
    }


def _cabecalho(indice_coluna: int) -> dict[str, Any]:
    return {
        "tipo_origem": "cabecalho_de_tabela",
        "arquivo_origem": "tables/table001.json",
        "seletor_coluna": {"indice_coluna_esperado": indice_coluna},
        "obrigatorio": True,
    }


def _candidato(contexto: dict[str, Any]) -> dict[str, Any]:
    """Preenche exatamente as entradas esperadas, com uma coluna por papel."""
    coluna = {"periodo_referencia": 1, "periodo_comparativo_anterior": 2, "mesmo_periodo_ano_anterior": 4}
    mapeamento: dict[str, Any] = {}
    for entrada in contexto["llm_payloads"]["candidate_generation"]["entradas_esperadas"]:
        papel = entrada["seletores"]["papel_periodo"]
        mapeamento[entrada["chave"]] = (
            _celula(coluna[papel]) if entrada["campo"] == "valor" else _cabecalho(coluna[papel])
        )
    return {
        "tipo_artefato": "layout_signature_candidato",
        "status_layout": "candidato",
        "escopo_correcao": "criacao_inicial_layout",
        "document_id": "doc-1",
        "execution_id_origem": "exec-1",
        "base_layout_signature": None,
        "fontes_relevantes": {},
        "regras_deteccao_mudanca": [],
        "campos_nao_mapeados": [],
        "mapeamento_canonico": mapeamento,
        "metadados_estruturais_evidencia": {},
    }


# --- payload -----------------------------------------------------------------


def test_payload_do_candidato_leva_as_entradas_fechadas_e_a_identidade(contexto: dict[str, Any]) -> None:
    payload = contexto["llm_payloads"]["candidate_generation"]
    assert payload["identidade_documento"] == IDENTIDADE
    assert len(payload["entradas_esperadas"]) == 12
    assert all("[empresa=cury]" in entrada["chave"] for entrada in payload["entradas_esperadas"])
    # A selecao de artefatos nao recebe a lista: ela escolhe onde procurar, nao o que escrever.
    assert "entradas_esperadas" not in contexto["llm_payloads"]["artifact_selection"]


def test_sem_identidade_o_payload_nao_muda(contrato: dict[str, Any]) -> None:
    builder = FallbackProblemContextBuilder()
    contexto = {
        "escopo_permitido": "criacao_inicial_layout",
        "fallback_context": EXECUCAO,
        "contrato_semantico_relevante": builder._relevant_contract_context(contract=contrato, broken_fields=[]),
        "inventario_extracao": {"resumo": {"items": []}},
    }
    payload = builder.build_llm_payloads(contexto)["candidate_generation"]
    assert "entradas_esperadas" not in payload
    assert "identidade_documento" not in payload


def test_projecao_do_contrato_expoe_paths_derivados(contexto: dict[str, Any]) -> None:
    estrutura = contexto["contrato_semantico_relevante"]["estrutura_schema_saida"]
    assert "fonte" in estrutura["paths_derivados"]
    assert "periodos_disponiveis.periodo_referencia" in estrutura["paths_derivados"]


# --- mensagens ---------------------------------------------------------------


class _Montador(CandidateJsonGenerationMixin):
    def __init__(self) -> None:
        self.registrados: list[dict] = []

    def _registrar_prompts(self, utilizados: list[dict], *, conjunto: str | None = None) -> None:
        self.registrados = utilizados


def test_entradas_esperadas_entram_no_bloco_de_contrato_da_primeira_geracao(contexto: dict[str, Any]) -> None:
    payload = contexto["llm_payloads"]["candidate_generation"]
    mensagens = _Montador()._initial_candidate_messages(payload)
    bloco = json.loads(mensagens[3]["content"])
    assert list(bloco) == [
        "contrato_semantico_relevante",
        "alvos_mapeaveis",
        "identidade_documento",
        "entradas_esperadas",
    ]
    assert bloco["entradas_esperadas"] == payload["entradas_esperadas"]
    assert "entradas_esperadas" in mensagens[2]["content"]


# --- fragmento por unidade -----------------------------------------------------


class _Unidades(MappingUnitGenerationMixin):
    mapping_plan_service = MAPPING_PLAN_SERVICE


def test_cada_unidade_recebe_so_as_entradas_dos_seus_requisitos(contexto: dict[str, Any]) -> None:
    payload = contexto["llm_payloads"]["candidate_generation"]
    unidades = MAPPING_PLAN_SERVICE.build(contexto["contrato_semantico_relevante"])
    assert len(unidades) == 1  # construtoras tem uma raiz semantica
    fragmento = _Unidades()._fragment_payload_for_unit(
        candidate_payload=payload, unit=unidades[0], loaded_artifacts={}
    )
    assert fragmento["identidade_documento"] == IDENTIDADE
    assert {entrada["requisito"] for entrada in fragmento["entradas_esperadas"]} == set(unidades[0].paths)
    assert len(fragmento["entradas_esperadas"]) == 12


# --- validador ---------------------------------------------------------------


def test_candidato_com_as_chaves_exatas_passa(contexto: dict[str, Any]) -> None:
    modelo = FallbackCandidateValidationService().validate_candidate_layout(_candidato(contexto), contexto)
    assert len(modelo.mapeamento_canonico) == 12


def test_nome_da_origem_no_lugar_do_slug_e_recusado_com_a_chave_certa(contexto: dict[str, Any]) -> None:
    """O caso Direcional do lote 7 deixa de depender de prompt."""
    candidato = _candidato(contexto)
    errada = (
        "balancos_das_empresas.lancamentos.dados[empresa=identidade_documento]"
        ".valores[papel_periodo=periodo_referencia].valor"
    )
    certa = errada.replace("identidade_documento", "cury")
    candidato["mapeamento_canonico"][errada] = candidato["mapeamento_canonico"].pop(certa)
    with pytest.raises(RuntimeError) as excecao:
        FallbackCandidateValidationService().validate_candidate_layout(candidato, contexto)
    mensagem = str(excecao.value)
    assert "fora de entradas_esperadas" in mensagem
    assert certa in mensagem


def test_chave_de_item_preenchida_pelo_seletor_e_recusada_como_extra(contexto: dict[str, Any]) -> None:
    candidato = _candidato(contexto)
    candidato["mapeamento_canonico"]["balancos_das_empresas.lancamentos.dados[empresa=cury].empresa"] = {
        "tipo_origem": "valor_fixo",
        "valor_fixo": "Cury",
        "obrigatorio": True,
    }
    with pytest.raises(RuntimeError) as excecao:
        FallbackCandidateValidationService().validate_candidate_layout(candidato, contexto)
    assert "Remova a chave" in str(excecao.value)


def test_sem_identidade_no_contexto_a_regra_nao_se_aplica(contexto: dict[str, Any]) -> None:
    candidato = _candidato(contexto)
    candidato["mapeamento_canonico"]["balancos_das_empresas.lancamentos.dados[empresa=cury].empresa"] = {
        "tipo_origem": "valor_fixo",
        "valor_fixo": "Cury",
        "obrigatorio": True,
    }
    legado = {chave: valor for chave, valor in contexto.items() if chave != "identidade_documento"}
    FallbackCandidateValidationService().validate_candidate_layout(candidato, legado)


def test_correcao_parcial_preserva_chaves_anteriores_do_layout_base(contexto: dict[str, Any]) -> None:
    candidato = _candidato(contexto)
    candidato["escopo_correcao"] = "correcao_parcial_mapeamento"
    candidato["base_layout_signature"] = {"versao": "1.3.0", "object_key": "layouts/x/v1.3.0/l.json"}
    antiga = "balancos_das_empresas.lancamentos.dados[empresa=cury].empresa"
    candidato["mapeamento_canonico"][antiga] = {"tipo_origem": "valor_fixo", "valor_fixo": "Cury", "obrigatorio": True}
    parcial = {
        **contexto,
        "escopo_permitido": "correcao_parcial_mapeamento",
        "layout_signature_base_ref": {"versao": "1.3.0", "object_key": "layouts/x/v1.3.0/l.json"},
        "layout_signature_base_validation_context": {
            "mapeamento_canonico_paths": [antiga, *candidato["mapeamento_canonico"]],
            "regras_deteccao_mudanca_ids": [],
        },
    }
    FallbackCandidateValidationService().validate_candidate_layout(candidato, parcial)


# --- identidade do documento --------------------------------------------------


def test_identidade_vem_do_slug_da_conf_e_do_periodo_do_manifesto() -> None:
    identidade = FallbackContextLoadingMixin._document_identity(
        {"entity_slug": "cyre3", "entity_name": "Cyrela"},
        {"candidate": {"entity_name": "Cereal", "period_label": "2T26"}},
    )
    assert identidade == {"entidade": "cyre3", "entidade_nome": "Cyrela", "periodo": "2T26"}


def test_identidade_omite_periodo_vazio_em_vez_de_inventar() -> None:
    identidade = FallbackContextLoadingMixin._document_identity(
        {"entity_slug": "cyre3"}, {"candidate": {"period_label": "  "}}
    )
    assert identidade == {"entidade": "cyre3"}
