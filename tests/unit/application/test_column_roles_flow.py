"""Fase 2 no fluxo da DAG 3: estrutura das tabelas e coluna por papel no payload e no validador.

Cobre o caminho inteiro sem MinIO, LLM nem Airflow: contrato com ``papeis.*.derivacao``
+ identidade com periodo -> payload de unidade com ``estrutura_tabelas`` e
``ancoragem_resolvida.indice_coluna`` -> validador recusando coluna diferente da
resolvida pelo contrato.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from document_processing.application.use_cases.fallback import prompt_sets
from document_processing.application.use_cases.fallback._common import contract_and_targets_block
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
CABECALHOS = ["", "2T26", "1T26", "%T/T", "2T25", "%A/A", "2T26 UDM*"]
TABELA_LANCAMENTOS = {
    "schema": ["Lançamentos", *CABECALHOS[1:]],
    "rows": [
        ["VGV (R$ milhões)", "1,0", "0,9", "11%", "0,8", "25%", "3,0"],
        ["Unidades Lançadas", "1000", "900", "11%", "800", "25%", "3000"],
    ],
}
TABELA_VENDAS = {
    "schema": ["Vendas", *CABECALHOS[1:]],
    "rows": [
        ["Vendas Contratadas Brutas (Unidades)", "3601", "3536", "2%", "3570", "1%", "9000"],
        ["Vendas Líquidas 100% (Unid.)", "3351", "3105", "8%", "3136", "7%", "8000"],
    ],
}
def _envelope(object_key: str, tabela: dict[str, Any]) -> dict[str, Any]:
    """Forma real de ``loaded_artifacts`` em producao (nao a tabela crua).

    ``inventory_loading.load_artifact_for_llm`` embrulha todo artefato que
    cabe inteiro no contexto em ``{object_key, formato, sample}`` — o
    ``schema``/``rows`` fica dentro de ``sample``, nunca na raiz. Um bug real
    (achado no lote 10, corrigido em seguida) leu ``rows`` na raiz e nunca viu
    tabela nenhuma; por isso os fixtures usam a forma embrulhada, nao a crua.
    """
    return {"object_key": object_key, "formato": "json", "sample": {"kind": "table", **tabela}}


ARTEFATOS_CARREGADOS = {
    "tables/table001.json": _envelope("tables/table001.json", TABELA_LANCAMENTOS),
    "tables/table002.json": _envelope("tables/table002.json", TABELA_VENDAS),
}
COLUNA_CERTA = {"periodo_referencia": 1, "periodo_comparativo_anterior": 2, "mesmo_periodo_ano_anterior": 4}


@pytest.fixture(scope="module")
def contrato() -> dict[str, Any]:
    caminho = next((CONTRATOS / "construtoras" / "v1.9.1").glob("*.json"))
    return json.loads(caminho.read_text(encoding="utf-8"))


def _contexto(contrato: dict[str, Any], identidade: dict[str, str]) -> dict[str, Any]:
    builder = FallbackProblemContextBuilder()
    projetado = builder._relevant_contract_context(contract=contrato, broken_fields=[])
    contexto = {
        "escopo_permitido": "criacao_inicial_layout",
        "fallback_context": EXECUCAO,
        "contrato_semantico_relevante": projetado,
        "inventario_extracao": {"resumo": {"items": []}},
        "identidade_documento": identidade,
        "_paths_fixos_do_contrato": [],
        "layout_signature_base_ref": None,
    }
    contexto["llm_payloads"] = builder.build_llm_payloads(contexto)
    return contexto


@pytest.fixture
def contexto(contrato: dict[str, Any]) -> dict[str, Any]:
    return _contexto(contrato, IDENTIDADE)


@pytest.fixture(autouse=True)
def _sem_langfuse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLAS_PROMPTS_LANGFUSE_ENABLED", raising=False)
    prompt_sets.LANGFUSE_PROMPT_REGISTRY.limpar_cache()


class _Unidades(MappingUnitGenerationMixin):
    mapping_plan_service = MAPPING_PLAN_SERVICE


def _fragmento(contexto: dict[str, Any]) -> dict[str, Any]:
    payload = contexto["llm_payloads"]["candidate_generation"]
    unidade = MAPPING_PLAN_SERVICE.build(contexto["contrato_semantico_relevante"])[0]
    return _Unidades()._fragment_payload_for_unit(
        candidate_payload=payload, unit=unidade, loaded_artifacts=ARTEFATOS_CARREGADOS
    )


def test_fragmento_traz_a_estrutura_das_tabelas_com_papel_por_coluna(contexto: dict[str, Any]) -> None:
    fragmento = _fragmento(contexto)
    estrutura = fragmento["estrutura_tabelas"]
    assert set(estrutura) == set(ARTEFATOS_CARREGADOS)
    vendas = estrutura["tables/table002.json"]
    assert vendas["coluna_rotulo"] == 0
    assert vendas["cabecalho_lido"] is True
    assert vendas["origem_papeis"] == "contrato"
    assert vendas["papel_por_coluna"] == {
        "papel_periodo": {
            "1": "periodo_referencia",
            "2": "periodo_comparativo_anterior",
            "4": "mesmo_periodo_ano_anterior",
        }
    }
    # O bloco enviado a LLM leva a estrutura junto com as entradas esperadas.
    assert "estrutura_tabelas" in contract_and_targets_block(fragmento)


def test_ancoragem_resolvida_ganha_a_coluna_do_papel(contexto: dict[str, Any]) -> None:
    fragmento = _fragmento(contexto)
    por_grupo_e_papel = {
        (e["requisito"].split(".")[1], e["seletores"]["papel_periodo"]): e["ancoragem_resolvida"]
        for e in fragmento["entradas_esperadas"]
        if e["campo"] == "valor" and "ancoragem_resolvida" in e
    }
    assert len(por_grupo_e_papel) == 6
    linhas = {"lancamentos": ("tables/table001.json", "Unidades Lançadas"), "vendas": ("tables/table002.json", "Vendas Contratadas Brutas (Unidades)")}
    for (grupo, papel), ancoragem in por_grupo_e_papel.items():
        assert (ancoragem["arquivo_origem"], ancoragem["rotulo_linha"]) == linhas[grupo]
        assert ancoragem["indice_coluna"] == COLUNA_CERTA[papel]
        assert ancoragem["cabecalho_coluna"] == CABECALHOS[COLUNA_CERTA[papel]]


def _entrada(tipo: str, *, arquivo: str, rotulo: str, indice_linha: int, coluna: int) -> dict[str, Any]:
    entrada: dict[str, Any] = {
        "tipo_origem": tipo,
        "arquivo_origem": arquivo,
        "seletor_coluna": {"indice_coluna_esperado": coluna},
        "obrigatorio": True,
    }
    if tipo == "celula_de_tabela":
        entrada["seletor_linha"] = {
            "coluna_rotulo": 0,
            "valor_aceito": rotulo,
            "indice_linha_esperado": indice_linha,
        }
    return entrada


def _candidato(contexto: dict[str, Any], colunas: dict[str, dict[str, int]]) -> dict[str, Any]:
    """Candidato completo (12 chaves); ``colunas`` da a coluna por grupo e papel."""
    fontes = {
        "lancamentos": ("tables/table001.json", "Unidades Lançadas", 1),
        "vendas": ("tables/table002.json", "Vendas Contratadas Brutas (Unidades)", 0),
    }
    mapeamento: dict[str, Any] = {}
    for entrada in contexto["llm_payloads"]["candidate_generation"]["entradas_esperadas"]:
        grupo = entrada["requisito"].split(".")[1]
        papel = entrada["seletores"]["papel_periodo"]
        arquivo, rotulo, indice_linha = fontes[grupo]
        tipo = "celula_de_tabela" if entrada["campo"] == "valor" else "cabecalho_de_tabela"
        mapeamento[entrada["chave"]] = _entrada(
            tipo, arquivo=arquivo, rotulo=rotulo, indice_linha=indice_linha, coluna=colunas[grupo][papel]
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


def _validar(contexto: dict[str, Any], candidato: dict[str, Any]) -> Any:
    contexto_validacao = {**contexto, "artefatos_contexto_llm": ARTEFATOS_CARREGADOS}
    return FallbackCandidateValidationService().validate_candidate_layout(candidato, contexto_validacao)


def test_validador_aceita_as_colunas_resolvidas_pelo_contrato(contexto: dict[str, Any]) -> None:
    candidato = _candidato(contexto, {"lancamentos": COLUNA_CERTA, "vendas": COLUNA_CERTA})
    assert len(_validar(contexto, candidato).mapeamento_canonico) == 12


def test_validador_recusa_o_valor_numa_coluna_de_outro_papel(contexto: dict[str, Any]) -> None:
    """A LLM trocou a coluna de referencia pela do trimestre anterior (1T26)."""
    trocada = {**COLUNA_CERTA, "periodo_referencia": 2}
    candidato = _candidato(contexto, {"lancamentos": COLUNA_CERTA, "vendas": trocada})
    with pytest.raises(RuntimeError) as excecao:
        _validar(contexto, candidato)
    mensagem = str(excecao.value)
    assert "periodo_referencia" in mensagem
    assert "coluna 1 ('2T26')" in mensagem
    assert "tables/table002.json" in mensagem
    assert "indice_coluna_esperado=2" in mensagem


def test_validador_recusa_a_coluna_udm_com_sufixo_de_outro_escopo(contexto: dict[str, Any]) -> None:
    """O cabecalho de contexto (periodo) foi tirado da coluna '2T26 UDM*' em vez de '2T26'."""
    trocada = {**COLUNA_CERTA, "periodo_referencia": 6}
    candidato = _candidato(contexto, {"lancamentos": trocada, "vendas": COLUNA_CERTA})
    with pytest.raises(RuntimeError) as excecao:
        _validar(contexto, candidato)
    assert "tables/table001.json" in str(excecao.value)
    assert "coluna 1 ('2T26')" in str(excecao.value)


def test_sem_periodo_na_identidade_a_coluna_continua_livre(contrato: dict[str, Any]) -> None:
    contexto = _contexto(contrato, {"entidade": "plano-plano", "entidade_nome": "Plano&Plano"})
    fragmento = _fragmento(contexto)
    assert "papel_por_coluna" not in fragmento["estrutura_tabelas"]["tables/table002.json"]
    trocada = {**COLUNA_CERTA, "periodo_referencia": 6}
    candidato = _candidato(contexto, {"lancamentos": trocada, "vendas": trocada})
    assert len(_validar(contexto, candidato).mapeamento_canonico) == 12
