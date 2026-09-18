"""Fase 3.2 no fluxo da DAG 3: ancoragem de linha por sinonimo do contrato.

Cobre o caminho inteiro sem MinIO, LLM nem Airflow: contrato com sinonimo
especifico (item 3.2 do plano) -> payload de unidade com ancoragem_resolvida
-> validador recusando uma linha diferente da resolvida.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from document_processing.application.use_cases.fallback import prompt_sets
from document_processing.application.use_cases.fallback.context_builder import (
    FallbackProblemContextBuilder,
)
from document_processing.application.use_cases.fallback.mapping_unit_generation import (
    MappingUnitGenerationMixin,
)
from document_processing.domain.fallback.candidate_validation import (
    FallbackCandidateValidationService,
)
from document_processing.domain.fallback.mapping_plan import MAPPING_PLAN_SERVICE

CONTRATOS = Path("infra/minio-bootstrap/contracts")
IDENTIDADE = {"entidade": "plano-plano", "entidade_nome": "Plano&Plano", "periodo": "2T26"}
EXECUCAO = {
    "document_id": "doc-1",
    "execution_id": "exec-1",
    "manifest_key": "m",
    "entity_slug": "plano-plano",
}

TABELA_VENDAS = {
    "rows": [
        ["Vendas Contratadas Brutas (Unidades)", "3601", "3536", "3570"],
        ["Vendas Líquidas 100% (Unid.)", "3351", "3105", "3136"],
    ]
}
ARTEFATOS_CARREGADOS = {"tables/table002.json": TABELA_VENDAS}


@pytest.fixture(scope="module")
def contrato() -> dict[str, Any]:
    caminho = next((CONTRATOS / "construtoras" / "v1.9.1").glob("*.json"))
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


class _Unidades(MappingUnitGenerationMixin):
    mapping_plan_service = MAPPING_PLAN_SERVICE


def _celula(indice_coluna: int) -> dict[str, Any]:
    return {
        "tipo_origem": "celula_de_tabela",
        "arquivo_origem": "tables/table001.json",
        "seletor_linha": {
            "coluna_rotulo": 0,
            "valor_aceito": "Numero de Unidades",
            "indice_linha_esperado": 2,
        },
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


def test_fragmento_recebe_a_ancoragem_resolvida_quando_o_sinonimo_casa_uma_linha(
    contexto: dict[str, Any],
) -> None:
    payload = contexto["llm_payloads"]["candidate_generation"]
    unidade = MAPPING_PLAN_SERVICE.build(contexto["contrato_semantico_relevante"])[0]
    fragmento = _Unidades()._fragment_payload_for_unit(
        candidate_payload=payload, unit=unidade, loaded_artifacts=ARTEFATOS_CARREGADOS
    )
    entrada = next(
        e
        for e in fragmento["entradas_esperadas"]
        if e["requisito"].startswith("balancos_das_empresas.vendas")
        and e["seletores"].get("papel_periodo") == "periodo_referencia"
        and e["campo"] == "valor"
    )
    assert entrada["ancoragem_resolvida"] == {
        "arquivo_origem": "tables/table002.json",
        "rotulo_linha": "Vendas Contratadas Brutas (Unidades)",
        "indice_linha": 0,
    }
    # Lancamentos nao tem sinonimo especifico o bastante e nenhuma tabela de
    # lancamentos foi carregada: nao ganha ancoragem.
    lancamentos = [
        e for e in fragmento["entradas_esperadas"] if e["requisito"].startswith(
            "balancos_das_empresas.lancamentos"
        )
    ]
    assert all("ancoragem_resolvida" not in e for e in lancamentos)


def _celula_vendas(indice_coluna: int, *, rotulo: str, arquivo: str) -> dict[str, Any]:
    return {
        "tipo_origem": "celula_de_tabela",
        "arquivo_origem": arquivo,
        "seletor_linha": {
            "coluna_rotulo": 0,
            "valor_aceito": rotulo,
            "indice_linha_esperado": 0,
        },
        "seletor_coluna": {"indice_coluna_esperado": indice_coluna},
        "obrigatorio": True,
    }


def _candidato_vendas(contexto: dict[str, Any], *, rotulo: str, arquivo: str) -> dict[str, Any]:
    """Candidato completo (12 chaves); todas as 3 entradas de vendas.valor (mesma
    linha fisica, colunas diferentes) usam o rotulo/arquivo sob teste — os 3
    periodos resolvem para a mesma linha, so a coluna muda.
    """
    coluna = {"periodo_referencia": 1, "periodo_comparativo_anterior": 2, "mesmo_periodo_ano_anterior": 4}
    mapeamento: dict[str, Any] = {}
    for entrada in contexto["llm_payloads"]["candidate_generation"]["entradas_esperadas"]:
        papel = entrada["seletores"]["papel_periodo"]
        eh_vendas_valor = (
            entrada["requisito"].startswith("balancos_das_empresas.vendas") and entrada["campo"] == "valor"
        )
        if eh_vendas_valor:
            mapeamento[entrada["chave"]] = _celula_vendas(coluna[papel], rotulo=rotulo, arquivo=arquivo)
        else:
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


def test_validador_aceita_a_linha_resolvida_por_sinonimo(contexto: dict[str, Any]) -> None:
    candidato = _candidato_vendas(
        contexto,
        rotulo="Vendas Contratadas Brutas (Unidades)",
        arquivo="tables/table002.json",
    )
    contexto_validacao = {**contexto, "artefatos_contexto_llm": ARTEFATOS_CARREGADOS}
    modelo = FallbackCandidateValidationService().validate_candidate_layout(
        candidato, contexto_validacao
    )
    assert len(modelo.mapeamento_canonico) == 12


def test_validador_recusa_a_linha_ambigua_escolhida_pela_llm(contexto: dict[str, Any]) -> None:
    """O caso Plano&Plano do lote 7: a LLM escolheu 'Liquidas' em vez de 'Brutas'."""
    candidato = _candidato_vendas(
        contexto,
        rotulo="Vendas Líquidas 100% (Unid.)",
        arquivo="tables/table002.json",
    )
    contexto_validacao = {**contexto, "artefatos_contexto_llm": ARTEFATOS_CARREGADOS}
    with pytest.raises(RuntimeError) as excecao:
        FallbackCandidateValidationService().validate_candidate_layout(
            candidato, contexto_validacao
        )
    mensagem = str(excecao.value)
    assert "Vendas Contratadas Brutas (Unidades)" in mensagem
    assert "tables/table002.json" in mensagem


def test_sem_artefatos_carregados_o_validador_nao_verifica_nada(contexto: dict[str, Any]) -> None:
    candidato = _candidato_vendas(
        contexto,
        rotulo="Vendas Líquidas 100% (Unid.)",
        arquivo="tables/table002.json",
    )
    modelo = FallbackCandidateValidationService().validate_candidate_layout(candidato, contexto)
    assert len(modelo.mapeamento_canonico) == 12
